"""SavanaGeoAgent: the one agent class for savana - grounded Q&A, map
control, and a chat UI, all in one place.

This is the single, recommended entry point for AI-assisted interaction
with your savana results. Everything lives on one class so there's one
thing to import and one thing to remember, instead of several separate
pieces to keep straight:

    from savana.agents import SavanaGeoAgent

    agent = SavanaGeoAgent(clf, model="anthropic")
    agent.ask("How much core woodland is there in 2024?")   # grounded Q&A
    agent.ask("Show 2019 and 2024 on the map")               # map control
    agent.show_ui()                                          # chat UI + live map, inline

Built directly on Strands (the same engine geoai's own GeoAgent uses),
not through the standalone GeoAgent package — this avoids that package's
``max_tokens`` bug and gives full control over the tool set.

Requires: ``pip install "savana[agents]"``.
"""

from __future__ import annotations

import os
from typing import Any, Optional


def _require_strands():
    try:
        import strands  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "SavanaGeoAgent requires the optional 'agents' extra. "
            'Install with: pip install "savana[agents]"'
        ) from exc


def create_anthropic_model(
    model_id: str = "claude-sonnet-4-6",
    api_key: Optional[str] = None,
    max_tokens: int = 4096,
    client_args: Optional[dict] = None,
    **kwargs: Any,
):
    """Create a Strands AnthropicModel, with max_tokens always explicit.

    Always passing ``max_tokens`` (rather than only when the caller
    supplies one) is deliberate — omitting it causes a bare
    ``KeyError: 'max_tokens'`` in some Strands/Anthropic version
    combinations, since the Anthropic API requires it on every request.
    """
    from strands.models.anthropic import AnthropicModel

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "No Anthropic API key found. Set ANTHROPIC_API_KEY or pass api_key=."
        )
    client_args = dict(client_args or {})
    client_args.setdefault("api_key", api_key)
    return AnthropicModel(
        client_args=client_args, model_id=model_id, max_tokens=max_tokens, **kwargs
    )


def create_openai_model(
    model_id: str = "gpt-4o-mini",
    api_key: Optional[str] = None,
    client_args: Optional[dict] = None,
    **kwargs: Any,
):
    """Create a Strands OpenAIModel."""
    from strands.models.openai import OpenAIModel

    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "No OpenAI API key found. Set OPENAI_API_KEY or pass api_key=."
        )
    client_args = dict(client_args or {})
    client_args.setdefault("api_key", api_key)
    return OpenAIModel(client_args=client_args, model_id=model_id, **kwargs)


def create_gemini_model(
    model_id: str = "gemini-2.0-flash",
    api_key: Optional[str] = None,
    client_args: Optional[dict] = None,
    **kwargs: Any,
):
    """Create a Strands GeminiModel."""
    from strands.models.gemini import GeminiModel

    api_key = (
        api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    )
    if not api_key:
        raise ValueError(
            "No Gemini API key found. Set GEMINI_API_KEY/GOOGLE_API_KEY or pass api_key=."
        )
    client_args = dict(client_args or {})
    client_args.setdefault("api_key", api_key)
    return GeminiModel(client_args=client_args, model_id=model_id, **kwargs)


_MODEL_FACTORIES = {
    "anthropic": create_anthropic_model,
    "openai": create_openai_model,
    "gemini": create_gemini_model,
}


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


class _SavanaMapTools:
    """Map-control tools bound to a live geemap.Map, so the agent can put
    things on the map, not just answer questions about them."""

    def __init__(self, clf, map_instance=None):
        self.clf = clf
        self.map = map_instance
        self._layer_names: list[str] = []

    def _ensure_map(self):
        import geemap

        if self.map is None:
            self.map = geemap.Map()
            self.map.centerObject(self.clf.region, 12)
        return self.map

    def build_tools(self):
        from strands import tool

        from . import viz

        @tool(name="savana_show_year")
        def show_year(year: int) -> str:
            """Add a classified land-system year to the map as a new
            layer. The year must be one the classifier actually ran
            (check with savana_summarize if unsure which years exist)."""
            m = self._ensure_map()
            if year not in self.clf.maps:
                available = sorted(self.clf.maps.keys())
                return f"Year {year} was not classified. Available years: {available}"
            viz.show_classified_map(
                self.clf.maps[year],
                region=self.clf.region,
                class_info=self.clf.class_info,
                m=m,
            )
            name = f"Land System {year}"
            if name not in self._layer_names:
                self._layer_names.append(name)
            return f"Added {name} to the map."

        @tool(name="savana_show_all_years")
        def show_all_years() -> str:
            """Add every classified year to the map as separate,
            individually toggleable layers."""
            m = self._ensure_map()
            viz.show_multi_year_map(
                self.clf.maps,
                region=self.clf.region,
                class_info=self.clf.class_info,
                m=m,
            )
            for year in sorted(self.clf.maps.keys()):
                name = f"Land System {year}"
                if name not in self._layer_names:
                    self._layer_names.append(name)
            return f"Added all classified years to the map: {sorted(self.clf.maps.keys())}."

        @tool(name="savana_compare")
        def compare(left: str, right: str) -> str:
            """Side-by-side swipe comparison between two things on the
            map. Each of left/right is either a classified year (as a
            string, e.g. '2024') or a basemap name (e.g. 'SATELLITE',
            'HYBRID', 'ROADMAP')."""
            m = self._ensure_map()

            def _resolve(side: str):
                try:
                    year = int(side)
                except ValueError:
                    return side  # basemap name
                if year not in self.clf.maps:
                    raise ValueError(f"Year {year} was not classified.")
                return self.clf.maps[year]

            try:
                left_val, right_val = _resolve(left), _resolve(right)
            except ValueError as exc:
                return str(exc)
            viz.compare_split_map(
                left_val,
                right_val,
                left_label=left,
                right_label=right,
                region=self.clf.region,
                class_info=self.clf.class_info,
                m=m,
            )
            return f"Added a swipe comparison between {left} and {right}."

        @tool(name="savana_center_map")
        def center_map() -> str:
            """Center and zoom the map on the classifier's AOI."""
            m = self._ensure_map()
            m.centerObject(self.clf.region, 12)
            return "Centered the map on the classified area."

        @tool(name="savana_list_map_layers")
        def list_map_layers() -> str:
            """List the names of layers currently added to the map by
            this agent (does not include the base map)."""
            if not self._layer_names:
                return "No savana layers have been added to the map yet."
            return "Layers on the map: " + ", ".join(self._layer_names)

        @tool(name="savana_remove_layer")
        def remove_layer(layer_name: str) -> str:
            """Remove a previously-added layer from the map by name
            (see savana_list_map_layers for exact names)."""
            m = self._ensure_map()
            try:
                for layer in list(m.layers):
                    if getattr(layer, "name", None) == layer_name:
                        m.remove_layer(layer)
                        if layer_name in self._layer_names:
                            self._layer_names.remove(layer_name)
                        return f"Removed {layer_name} from the map."
                return f"No layer named {layer_name!r} found on the map."
            except Exception as exc:  # noqa: BLE001
                return f"Could not remove layer: {type(exc).__name__}: {exc}"

        return [
            show_year,
            show_all_years,
            compare,
            center_map,
            list_map_layers,
            remove_layer,
        ]


DEFAULT_SYSTEM_PROMPT = """You are a geospatial analysis assistant for the savana package,
which classifies savanna landscapes into land-system management classes
(Core Woodland, Open Woodland, Shrub-Transition Savanna, Grassland,
Riparian/Wetland Vegetation, Anthropogenic Disturbance).

You have two kinds of tools:
- savana_* query tools (summarize, class_area, dominant_class, accuracy,
  change) answer questions using ONLY real computed results — never
  estimate or guess a figure yourself, and say so plainly if a tool can't
  answer something rather than inventing a plausible-sounding number.
- savana_show_year / savana_show_all_years / savana_compare /
  savana_center_map / savana_list_map_layers / savana_remove_layer put
  results on the interactive map or control what's shown."""


class SavanaGeoAgent:
    """The one agent class for savana: grounded Q&A + map control + chat UI.

    Args:
        clf: A ``SavanaClassifier`` that has already run.
        model: Either a provider name (``"anthropic"``, ``"openai"``,
            ``"gemini"`` — uses that provider's env-var API key and a
            sensible default model id) or an already-built Strands model
            instance for full control.
        model_id: Optional explicit model id, used only when ``model`` is
            a provider name string.
        map_instance: Optional existing ``geemap.Map`` to control. If
            omitted, one is created automatically (centered on the
            classifier's AOI) the first time a map tool is used.
        system_prompt: Overrides the default savana-scoped system prompt.
        **model_kwargs: Passed through to the model factory (e.g.
            ``api_key=``, ``max_tokens=``).
    """

    def __init__(
        self,
        clf,
        model: str = "anthropic",
        model_id: Optional[str] = None,
        map_instance=None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        **model_kwargs: Any,
    ):
        _require_strands()
        from strands import Agent

        self._qa_tools = _SavanaQATools(clf)
        self._map_tools = _SavanaMapTools(clf, map_instance=map_instance)

        if isinstance(model, str) and model.lower() in _MODEL_FACTORIES:
            factory = _MODEL_FACTORIES[model.lower()]
            kwargs = dict(model_kwargs)
            if model_id:
                kwargs["model_id"] = model_id
            model_instance = factory(**kwargs)
        elif isinstance(model, str):
            raise ValueError(
                f"Unknown provider {model!r}. Use one of {list(_MODEL_FACTORIES)}, "
                "or pass an already-built Strands model instance."
            )
        else:
            model_instance = model  # assume caller passed a real Strands model

        self._agent = Agent(
            name="Savana Land-System Agent",
            model=model_instance,
            system_prompt=system_prompt,
            tools=self._qa_tools.build_tools() + self._map_tools.build_tools(),
        )

    @property
    def map(self):
        """The live geemap.Map this agent controls (created on first use if not supplied)."""
        return self._map_tools._ensure_map()

    def ask(self, prompt: str) -> str:
        """Send a single-turn question, get a plain-text answer back."""
        result = self._agent(prompt)
        return getattr(result, "final_text", str(result))

    def __call__(self, prompt: str):
        """Full Strands result object (same as calling the agent directly)."""
        return self._agent(prompt)

    def show_ui(self, height: int = 500):
        """Display a live map + chat box side by side, inline in the notebook.

        Requires: ``ipywidgets`` (installed with the ``agents`` extra).
        """
        try:
            import ipywidgets as widgets
            from IPython.display import display
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "show_ui() requires ipywidgets. Install with: pip install ipywidgets"
            ) from exc

        m = self.map
        map_panel = widgets.VBox(
            [widgets.HTML("<b>Map</b>"), m],
            layout=widgets.Layout(
                flex="1 1 0%", min_width="480px", height=f"{height}px"
            ),
        )

        output = widgets.Output(
            layout=widgets.Layout(
                border="1px solid #ccc",
                padding="8px",
                height=f"{height - 60}px",
                overflow_y="auto",
            )
        )
        text_box = widgets.Text(
            placeholder="Ask about your results, or ask to show/compare years...",
            layout=widgets.Layout(width="80%"),
        )
        send_button = widgets.Button(description="Send", button_style="primary")

        history: list[str] = []

        def _render():
            output.clear_output(wait=True)
            with output:
                for line in history:
                    print(line)

        def _send(_=None):
            question = text_box.value.strip()
            if not question:
                return
            text_box.value = ""
            history.append(f"You: {question}")
            history.append("Agent is thinking...")
            _render()
            answer = self.ask(question)
            history.pop()
            history.append(f"Agent: {answer}")
            history.append("")
            _render()

        send_button.on_click(_send)
        text_box.on_submit(_send)

        chat_panel = widgets.VBox(
            [
                widgets.HTML("<b>Chat</b>"),
                output,
                widgets.HBox([text_box, send_button]),
            ],
            layout=widgets.Layout(flex="1 1 0%", min_width="360px"),
        )

        display(widgets.HBox([map_panel, chat_panel]))
