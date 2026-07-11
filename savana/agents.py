"""SavanaGeoAgent: the one agent class for savana - grounded Q&A, map
control, and a chat UI, all in one place.

This is built directly ON TOP of geoai's own agent infrastructure
(``geoai.agents``) rather than a parallel reimplementation: the map is a
real ``geoai.Map`` (leafmap/MapLibre-based, the same class geoai's own
demos use), map control comes from geoai's real, full-featured
``MapTools`` (fly_to, add_basemap, add_vector, add_raster, add_cog_layer,
remove_layer, and more), and model creation reuses geoai's own
``create_anthropic_model``/``create_openai_model``/``create_gemini_model``.
savana adds its own grounded Q&A tools (summarize, class_area, accuracy,
change, etc.) alongside geoai's map tools on one combined Strands agent.

    from savana.agents import SavanaGeoAgent

    agent = SavanaGeoAgent(clf, model="anthropic")
    agent.ask("How much core woodland is there in 2024?")   # savana Q&A
    agent.ask("Fly to the study area and add a satellite basemap")  # geoai map tools
    agent.show_ui()                                          # chat UI + live map, inline

Requires: ``pip install "savana[agents]"`` (installs ``geoai-py[agents]``,
which brings in ``strands-agents``, ``leafmap``, and the LLM provider
SDKs).
"""

from __future__ import annotations

from typing import Any, Optional


def _require_geoai_agents():
    try:
        import geoai.agents  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "SavanaGeoAgent requires the optional 'agents' extra. "
            'Install with: pip install "savana[agents]"'
        ) from exc


class _SavanaQATools:
    """Grounded savana query tools, bound to one fitted SavanaClassifier."""

    def __init__(self, clf):
        self.clf = clf
        self._facts_cache: Optional[dict] = None

    def _facts(self, force_refresh: bool = False) -> dict:
        from . import insights

        if force_refresh or self._facts_cache is None:
            self._facts_cache = insights.compute_facts(self.clf)
        return self._facts_cache

    def build_tools(self):
        from strands import tool

        from . import insights

        @tool(name="savana_summarize")
        def summarize() -> str:
            """Full plain-English summary of the savana classification
            results: area per class per epoch, dominant class, model
            accuracy, and change detection between epochs."""
            return insights.summarize(self._facts())

        @tool(name="savana_class_area")
        def class_area(class_name: str, year: Optional[int] = None) -> str:
            """Area (km2) and percentage of a specific land-system class
            (e.g. 'Core Woodland', 'Grassland Systems') in a given year.
            Uses the most recent epoch if year is omitted."""
            facts = self._facts()
            return insights.answer(
                facts, f"how much {class_name} is there in {year or ''}"
            )

        @tool(name="savana_dominant_class")
        def dominant_class(year: Optional[int] = None) -> str:
            """The dominant (largest-area) land-system class for a given
            epoch year. Uses the most recent epoch if year is omitted."""
            facts = self._facts()
            return insights.answer(facts, f"what is the dominant class in {year or ''}")

        @tool(name="savana_accuracy")
        def accuracy() -> str:
            """Overall accuracy and kappa of the primary classification
            model (AlphaEarth embeddings + phenology)."""
            facts = self._facts()
            return insights.answer(facts, "how accurate is the model")

        @tool(name="savana_change")
        def change() -> str:
            """Change detection between the first and last classified
            epoch: genuine structural change vs. rainfall-driven apparent
            change, as a percentage of total area. Needs 2+ epochs."""
            facts = self._facts()
            return insights.answer(facts, "what changed between the years")

        @tool(name="savana_refresh")
        def refresh() -> str:
            """Force-recompute savana's results from Earth Engine,
            discarding cached values. Slow — only call if the underlying
            classifier's data actually changed since the last question."""
            self._facts(force_refresh=True)
            return "Results refreshed from Earth Engine."

        return [summarize, class_area, dominant_class, accuracy, change, refresh]


# geoai's own system prompt for its map-control tools (verbatim, from
# geoai.agents.geo_agents.GeoAgent) — reused rather than rewritten, since
# its explicit "minimal parameters only" rules are what keep map-tool
# calls fast and reliable in geoai's own demos.
_GEOAI_MAP_SYSTEM_PROMPT = """
You are a map control agent. Call tools with MINIMAL parameters only.

CRITICAL: Treat all kwargs parameters as optional parameters.
CRITICAL: NEVER include optional parameters unless user explicitly asks for them.

TOOL CALL RULES:
- zoom_to(zoom=N) - ONLY zoom parameter, OMIT options completely
- add_cog_layer(url='X') - NEVER include bands, nodata, opacity, etc.
- fly_to(longitude=N, latitude=N) - NEVER include zoom parameter
- add_basemap(name='X') - NEVER include any other parameters
- add_marker(lng_lat=[lon,lat]) - NEVER include popup or options

- remove_layer(name='X') - call get_layer_names() to get the layer name closest to
the name of the layer you want to remove before calling this tool

- add_overture_3d_buildings(kwargs={}) - kwargs parameter required by tool validation
FORBIDDEN: Optional parameters, string representations like '{}' or '[1,2,3]'
REQUIRED: Minimal tool calls with only what's absolutely necessary
"""

_SAVANA_PROMPT_ADDENDUM = """

You ALSO have savana_* tools for the land-system classification loaded
in this session (Core Woodland, Open Woodland, Shrub-Transition Savanna,
Grassland, Riparian/Wetland Vegetation, Anthropogenic Disturbance).
Answer questions about area, dominant class, accuracy, or change using
ONLY those tools — never estimate or guess a figure yourself. To put
savana results on the map, use savana_show_year / savana_show_all_years
/ savana_show_change / savana_center_on_aoi — the generic map tools
(add_raster, add_cog_layer, etc.) don't know about savana's classified
results, since those are Earth Engine images, not files or COG URLs.
"""


class _SavanaMapTools:
    """Puts savana's classified (ee.Image) results onto the real geoai
    map, via leafmap's ``add_ee_layer`` — the generic geoai map tools
    (add_raster, add_cog_layer, etc.) expect file paths or COG URLs and
    have no way to display an ee.Image, so savana needs its own bridge
    for this specifically."""

    def __init__(self, clf, session):
        self.clf = clf
        self.session = session

    def build_tools(self):
        from strands import tool

        from . import config

        @tool(name="savana_show_year")
        def show_year(year: int) -> str:
            """Add a classified land-system year to the map as a new
            layer. The year must be one the classifier actually ran
            (check with savana_summarize if unsure which years exist)."""
            if year not in self.clf.maps:
                available = sorted(self.clf.maps.keys())
                return f"Year {year} was not classified. Available years: {available}"
            vis = config.class_vis_params(self.clf.class_info)
            self.session.m.add_ee_layer(
                self.clf.maps[year], vis, name=f"Land System {year}"
            )
            return f"Added Land System {year} to the map."

        @tool(name="savana_show_all_years")
        def show_all_years() -> str:
            """Add every classified year to the map as separate,
            individually toggleable layers."""
            vis = config.class_vis_params(self.clf.class_info)
            for year in sorted(self.clf.maps.keys()):
                self.session.m.add_ee_layer(
                    self.clf.maps[year], vis, name=f"Land System {year}"
                )
            return f"Added all classified years to the map: {sorted(self.clf.maps.keys())}."

        @tool(name="savana_show_change")
        def show_change() -> str:
            """Add conservative/genuine/variable change-detection layers
            to the map. Requires the classifier to have been run with
            2+ epochs (check savana_change first if unsure)."""
            if self.clf.change is None:
                return "No change detection available — classifier was run with < 2 epochs."
            chg = self.clf.change
            self.session.m.add_ee_layer(
                chg["conservative_change"].selfMask(),
                {"palette": ["8b0000"]},
                name="Conservative change",
            )
            self.session.m.add_ee_layer(
                chg["genuine_change"].selfMask(),
                {"palette": ["d73027"]},
                name="Genuine structural change",
            )
            self.session.m.add_ee_layer(
                chg["variable_change"].selfMask(),
                {"palette": ["fc8d59"]},
                name="Rainfall-driven apparent change",
            )
            return "Added change-detection layers to the map."

        @tool(name="savana_center_on_aoi")
        def center_on_aoi() -> str:
            """Center and zoom the map on the classifier's study area."""
            lng, lat = self.clf.region.centroid(maxError=1).coordinates().getInfo()
            self.session.m.set_center(lng, lat, zoom=11)
            return "Centered the map on the study area."

        return [show_year, show_all_years, show_change, center_on_aoi]


class SavanaGeoAgent:
    """The one agent class for savana: grounded Q&A + full map control + chat UI.

    Built on geoai's real ``Map``/``MapTools``/model-factory infrastructure
    (see module docstring) — savana adds its own grounded query tools
    alongside geoai's map-control tools on one combined agent.

    Args:
        clf: A ``SavanaClassifier`` that has already run.
        model: Either a provider name (``"anthropic"``, ``"openai"``,
            ``"gemini"``, ``"ollama"`` — uses that provider's env-var API
            key, or a local Ollama server, and a sensible default model
            id) or an already-built Strands model instance.
        model_id: Optional explicit model id, used only when ``model`` is
            a provider name string.
        map_instance: Optional existing ``geoai.Map`` (leafmap/MapLibre)
            to control. If omitted, geoai creates a default one.
        max_tokens: Explicit max output tokens for the Anthropic provider
            specifically — always set explicitly here (not left to
            provider defaults), since omitting it is what causes a bare
            ``KeyError: 'max_tokens'`` in some Strands/Anthropic version
            combinations.
        **model_kwargs: Passed through to geoai's model factory.
    """

    def __init__(
        self,
        clf,
        model: str = "anthropic",
        model_id: Optional[str] = None,
        map_instance=None,
        max_tokens: int = 4096,
        **model_kwargs: Any,
    ):
        _require_geoai_agents()
        from geoai.agents import MapTools
        from geoai.agents.map_tools import MapSession
        from strands import Agent

        # Shared chat state — a plain agent.ask("...") call in any cell
        # and typing into show_ui()'s own text box both write here, so
        # whichever is currently displayed stays in sync with the other.
        self._history: list[str] = []
        self._chat_output = None  # set by show_ui() once displayed

        # Import each provider's model factory individually — not every
        # installed geoai version has every provider (e.g. some older
        # versions lack create_gemini_model), so a missing one shouldn't
        # block using a provider that IS available.
        factories: dict = {}
        try:
            from geoai.agents import create_anthropic_model

            factories["anthropic"] = lambda **kw: create_anthropic_model(
                max_tokens=max_tokens, **kw
            )
        except ImportError:
            pass
        try:
            from geoai.agents import create_openai_model

            factories["openai"] = create_openai_model
        except ImportError:
            pass
        try:
            from geoai.agents import create_gemini_model

            factories["gemini"] = create_gemini_model
        except ImportError:
            pass
        try:
            from geoai.agents import create_ollama_model

            factories["ollama"] = create_ollama_model
        except ImportError:
            pass

        # Real geoai map + map tools — not a savana-specific reimplementation.
        self._session = MapSession(map_instance)
        self._map_tools = MapTools(self._session)

        # Add the layer-toggle panel ONCE, up front — it's a live,
        # reactive MapLibre control that automatically tracks every layer
        # added afterward by any tool. Calling it again per-layer (an
        # earlier version of this code did that) risks stacking duplicate
        # panels instead of just staying in sync.
        try:
            self._session.m.add_layer_control()
        except Exception as exc:  # noqa: BLE001
            import warnings

            warnings.warn(
                f"Could not add the layer toggle panel: {type(exc).__name__}: {exc}",
                stacklevel=2,
            )

        self._qa_tools = _SavanaQATools(clf)
        self._savana_map_tools = _SavanaMapTools(clf, self._session)

        if isinstance(model, str) and model.lower() in factories:
            kwargs = dict(model_kwargs)
            if model_id:
                kwargs["model_id"] = model_id
            model_instance = factories[model.lower()](**kwargs)
        elif isinstance(model, str):
            raise ValueError(
                f"Provider {model!r} is not available (either unknown, or your "
                f"installed geoai version doesn't export its model factory). "
                f"Available in this environment: {list(factories)}, "
                "or pass an already-built Strands model instance."
            )
        else:
            model_instance = model  # assume caller passed a real Strands model

        map_tool_names = [
            "fly_to",
            "create_map",
            "zoom_to",
            "jump_to",
            "add_basemap",
            "add_vector",
            "add_raster",
            "add_cog_layer",
            "remove_layer",
            "get_layer_names",
            "set_terrain",
            "remove_terrain",
            "add_overture_3d_buildings",
            "set_paint_property",
            "set_layout_property",
            "set_color",
            "set_opacity",
            "set_visibility",
            "add_marker",
            "set_pitch",
        ]
        map_tools = [getattr(self._map_tools, name) for name in map_tool_names]

        self._agent = Agent(
            name="Savana Land-System Agent",
            model=model_instance,
            system_prompt=_GEOAI_MAP_SYSTEM_PROMPT + _SAVANA_PROMPT_ADDENDUM,
            tools=map_tools
            + self._qa_tools.build_tools()
            + self._savana_map_tools.build_tools(),
            callback_handler=None,
        )

    @property
    def map(self):
        """The live geoai.Map (leafmap/MapLibre) this agent controls."""
        return self._session.m

    def ask(self, prompt: str) -> str:
        """Send a single-turn question, get a plain-text answer back.

        If show_ui() is currently displayed, this also updates it —
        asking from a plain cell and typing into the UI box both write
        to the same visible chat log.
        """
        self._history.append(f"You: {prompt}")
        self._history.append("Agent is thinking...")
        self._render_chat()
        try:
            result = self._agent(prompt)
            answer = getattr(result, "final_text", str(result))
        except Exception as exc:  # noqa: BLE001
            self._history.pop()
            self._history.append(f"Agent error: {type(exc).__name__}: {exc}")
            self._history.append("")
            self._render_chat()
            raise
        self._history.pop()
        self._history.append(f"Agent: {answer}")
        self._history.append("")
        self._render_chat()
        return answer

    def _render_chat(self):
        """Redraw the show_ui() chat panel, if one is currently displayed."""
        if self._chat_output is None:
            return
        self._chat_output.clear_output(wait=True)
        with self._chat_output:
            for line in self._history:
                print(line)

    def __call__(self, prompt: str):
        """Full Strands result object (same as calling the agent directly)."""
        return self._agent(prompt)

    def show_ui(self, height: int = 600):
        """Display the live geoai map + a chat box side by side, inline.

        Calling ``agent.ask(...)`` in a separate cell also updates this
        panel, if it's currently displayed — they share the same chat log.

        Requires: ``ipywidgets`` (installed with the ``agents`` extra).
        """
        try:
            import ipywidgets as widgets
            from IPython.display import display
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "show_ui() requires ipywidgets. Install with: pip install ipywidgets"
            ) from exc

        map_panel = widgets.VBox(
            [widgets.HTML("<b>Map</b>"), self.map],
            layout=widgets.Layout(
                flex="1 1 0%", min_width="480px", height=f"{height}px"
            ),
        )

        self._chat_output = widgets.Output(
            layout=widgets.Layout(
                border="1px solid #ccc",
                padding="8px",
                height=f"{height - 60}px",
                overflow_y="auto",
            )
        )
        self._render_chat()  # show anything already asked before show_ui() was called

        text_box = widgets.Text(
            placeholder="Ask about your results, or ask to fly/add basemap/compare...",
            layout=widgets.Layout(width="80%"),
        )
        send_button = widgets.Button(description="Send", button_style="primary")

        def _send(_=None):
            question = text_box.value.strip()
            if not question:
                return
            text_box.value = ""
            try:
                self.ask(question)
            except Exception:  # noqa: BLE001
                pass  # already recorded to chat by ask() itself

        send_button.on_click(_send)
        text_box.on_submit(_send)

        chat_panel = widgets.VBox(
            [
                widgets.HTML("<b>Chat</b>"),
                self._chat_output,
                widgets.HBox([text_box, send_button]),
            ],
            layout=widgets.Layout(flex="1 1 0%", min_width="360px"),
        )

        display(widgets.HBox([map_panel, chat_panel]))
