"""GeoAgent integration: expose savana's grounded results as LLM tools.

This registers a `SavanaClassifier`'s own computed facts as GeoAgent tools,
following the same factory pattern GeoAgent already uses for `for_leafmap`
and `for_anymap`. The agent can then answer questions by *calling* these
tools — meaning, same as everywhere else in savana, it can only ever
report numbers the pipeline actually computed. It cannot invent area
figures, accuracy scores, or change percentages that aren't real.

Requires: ``pip install "savana[agent]"`` and a configured LLM provider
(e.g. ``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, or ``GEMINI_API_KEY`` set
as an environment variable — see GeoAgent's own provider setup docs).

Example
-------
>>> import savana
>>> from savana.agent import for_savana
>>>
>>> clf = savana.classify_landscape(aoi=..., epochs=[2019, 2024], park_name="Kyabobo")
>>> agent = for_savana(clf)
>>> resp = agent.chat("How much core woodland is there in 2024?")
>>> print(resp.answer_text)

Note on GeoLibre's embedded chat panel specifically: GeoLibre's built-in
"GeoAgent" map panel defaults to a browser-only mode with no connection to
this Python process, so it cannot call these tools as-is. Reaching it from
inside the GeoLibre map UI (rather than a notebook cell, as above) requires
switching that panel to GeoAgent's Python-backed WebSocket mode and is a
separate, larger integration step — not yet built here.
"""

from __future__ import annotations


def for_savana(
    clf,
    provider: str | None = None,
    model_id: str | None = None,
    max_tokens: int = 4096,
):
    """Create a GeoAgent bound to a fitted SavanaClassifier's real results.

    LLM provider selection follows GeoAgent's own environment-variable
    auto-detection by default (e.g. set ``OPENAI_API_KEY``,
    ``ANTHROPIC_API_KEY``, or ``GEMINI_API_KEY``/``GOOGLE_API_KEY`` before
    calling this). If that auto-detection misbehaves for your installed
    GeoAgent version, pass ``provider``/``model_id`` explicitly to bypass
    it — e.g. ``for_savana(clf, provider="anthropic", model_id="claude-sonnet-4-6")``.

    Args:
        clf: A ``SavanaClassifier`` that has already run (``clf.run()`` or
            at least ``.classify()`` completed) — the tools below read
            from its computed results, not from a raw/unfitted instance.
        provider: Optional explicit provider name (e.g. ``"anthropic"``,
            ``"openai"``, ``"gemini"``), passed straight through to
            GeoAgent's ``create_agent()``.
        model_id: Optional explicit model identifier for that provider,
            passed straight through to GeoAgent's ``create_agent()``.
        max_tokens: Explicit max output tokens, passed via GeoAgentConfig.
            Some GeoAgent/provider combinations fail with a bare
            ``'max_tokens'`` KeyError when this isn't set explicitly —
            passing it here works around that.

    Returns:
        A GeoAgent instance with savana-specific tools registered. Call
        ``agent.chat("...")`` to ask it questions.
    """
    try:
        from geoagent import GeoAgentConfig, GeoAgentContext, create_agent, geo_tool
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "The GeoAgent integration requires the optional 'agent' extra. "
            'Install with: pip install "savana[agent]"'
        ) from exc

    from . import insights

    # Cache computed facts per agent session — every tool below reads from
    # this instead of independently re-running the full Earth Engine
    # pipeline on every call. Without this, an agent that tries more than
    # one tool while answering a single question multiplies an already
    # expensive computation, which is what was causing multi-minute waits.
    _facts_cache: dict = {"value": None}

    def _get_facts(force_refresh: bool = False) -> dict:
        if force_refresh or _facts_cache["value"] is None:
            _facts_cache["value"] = insights.compute_facts(clf)
        return _facts_cache["value"]

    @geo_tool(category="savana")
    def savana_summarize() -> str:
        """Full plain-English summary of the savana classification results:
        area per class per epoch, dominant class, model accuracy, and
        change detection between epochs (if multiple years were run)."""
        return insights.summarize(_get_facts())

    @geo_tool(category="savana")
    def savana_class_area(class_name: str, year: int | None = None) -> str:
        """Area (km2) and percentage of a specific land-system class
        (e.g. 'Core Woodland', 'Grassland Systems') in a given year.
        Uses the most recent epoch if year is omitted."""
        facts = _get_facts()
        return insights.answer(facts, f"how much {class_name} is there in {year or ''}")

    @geo_tool(category="savana")
    def savana_dominant_class(year: int | None = None) -> str:
        """The dominant (largest-area) land-system class for a given
        epoch year. Uses the most recent epoch if year is omitted."""
        facts = _get_facts()
        return insights.answer(facts, f"what is the dominant class in {year or ''}")

    @geo_tool(category="savana")
    def savana_accuracy() -> str:
        """Overall accuracy and kappa of the primary classification model
        (AlphaEarth embeddings + phenology) for this classifier's results."""
        facts = _get_facts()
        return insights.answer(facts, "how accurate is the model")

    @geo_tool(category="savana")
    def savana_change() -> str:
        """Change detection between the first and last classified epoch:
        genuine structural change vs. rainfall-driven apparent change,
        as a percentage of the total area. Only meaningful if the
        classifier was run with 2+ epochs."""
        facts = _get_facts()
        return insights.answer(facts, "what changed between the years")

    @geo_tool(category="savana")
    def savana_refresh() -> str:
        """Force-recompute savana's results from Earth Engine, discarding
        the cached values. Use this only if you know the classifier's
        underlying data changed since the last question was answered —
        it's slow (a full pipeline re-run), so don't call it speculatively."""
        _get_facts(force_refresh=True)
        return "Results refreshed from Earth Engine."

    config = GeoAgentConfig(max_tokens=max_tokens)

    return create_agent(
        context=GeoAgentContext(),
        tools=[
            savana_summarize,
            savana_class_area,
            savana_dominant_class,
            savana_accuracy,
            savana_change,
            savana_refresh,
        ],
        config=config,
        provider=provider,
        model_id=model_id,
    )


def chat_widget(agent):
    """A real interactive chat box for a savana agent, inline in the notebook.

    Unlike calling ``agent.chat(...)`` in separate cells, this renders a
    single persistent text box + send button + scrolling conversation
    history — closer to an actual chat UI, without needing GeoLibre's
    (currently unavailable) browser-side agent bridge.

    Requires: ``ipywidgets`` (already installed in most Jupyter/JupyterLab
    setups; if not: ``pip install ipywidgets``).

    >>> agent = for_savana(clf)
    >>> savana.agent.chat_widget(agent)
    """
    try:
        import ipywidgets as widgets
        from IPython.display import display
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "chat_widget() requires ipywidgets. Install with: pip install ipywidgets"
        ) from exc

    output = widgets.Output(
        layout=widgets.Layout(
            border="1px solid #ccc", padding="8px", height="320px", overflow_y="auto"
        )
    )
    text_box = widgets.Text(
        placeholder="Ask about your savana results...",
        layout=widgets.Layout(width="80%"),
    )
    send_button = widgets.Button(description="Send", button_style="primary")
    row = widgets.HBox([text_box, send_button])

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

        resp = agent.chat(question)

        history.pop()  # remove the transient "thinking..." line
        if resp.success and resp.answer_text:
            history.append(f"Agent: {resp.answer_text}")
        else:
            history.append(f"Agent error: {resp.error_message or 'no response'}")
        history.append("")
        _render()

    send_button.on_click(_send)
    text_box.on_submit(_send)

    display(widgets.VBox([output, row]))
