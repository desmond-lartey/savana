"""GeoAgent integration: expose savana's grounded results as LLM tools.

This registers a `SavanaClassifier`'s own computed facts as GeoAgent tools,
following the same factory pattern GeoAgent already uses for `for_leafmap`
and `for_anymap`. The agent can then answer questions by *calling* these
tools — meaning, same as everywhere else in savana, it can only ever
report numbers your pipeline actually computed. It cannot invent area
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


def for_savana(clf):
    """Create a GeoAgent bound to a fitted SavanaClassifier's real results.

    LLM provider selection follows GeoAgent's own environment-variable
    auto-detection (e.g. set ``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, or
    ``GEMINI_API_KEY``/``GOOGLE_API_KEY`` before calling this) — see
    GeoAgent's provider setup documentation for the full list and for
    explicit ``GeoAgentConfig`` configuration if you need a non-default
    provider or model.

    Args:
        clf: A ``SavanaClassifier`` that has already run (``clf.run()`` or
            at least ``.classify()`` completed) — the tools below read
            from its computed results, not from a raw/unfitted instance.

    Returns:
        A GeoAgent instance with savana-specific tools registered. Call
        ``agent.chat("...")`` to ask it questions.
    """
    try:
        from geoagent import GeoAgentContext, create_agent, geo_tool
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "The GeoAgent integration requires the optional 'agent' extra. "
            'Install with: pip install "savana[agent]"'
        ) from exc

    from . import insights

    @geo_tool(category="savana")
    def savana_summarize() -> str:
        """Full plain-English summary of the savana classification results:
        area per class per epoch, dominant class, model accuracy, and
        change detection between epochs (if multiple years were run)."""
        return insights.summarize(insights.compute_facts(clf))

    @geo_tool(category="savana")
    def savana_class_area(class_name: str, year: int | None = None) -> str:
        """Area (km2) and percentage of a specific land-system class
        (e.g. 'Core Woodland', 'Grassland Systems') in a given year.
        Uses the most recent epoch if year is omitted."""
        facts = insights.compute_facts(clf)
        return insights.answer(facts, f"how much {class_name} is there in {year or ''}")

    @geo_tool(category="savana")
    def savana_dominant_class(year: int | None = None) -> str:
        """The dominant (largest-area) land-system class for a given
        epoch year. Uses the most recent epoch if year is omitted."""
        facts = insights.compute_facts(clf)
        return insights.answer(facts, f"what is the dominant class in {year or ''}")

    @geo_tool(category="savana")
    def savana_accuracy() -> str:
        """Overall accuracy and kappa of the primary classification model
        (AlphaEarth embeddings + phenology) for this classifier's results."""
        facts = insights.compute_facts(clf)
        return insights.answer(facts, "how accurate is the model")

    @geo_tool(category="savana")
    def savana_change() -> str:
        """Change detection between the first and last classified epoch:
        genuine structural change vs. rainfall-driven apparent change,
        as a percentage of the total area. Only meaningful if the
        classifier was run with 2+ epochs."""
        facts = insights.compute_facts(clf)
        return insights.answer(facts, "what changed between the years")

    return create_agent(
        context=GeoAgentContext(),
        tools=[
            savana_summarize,
            savana_class_area,
            savana_dominant_class,
            savana_accuracy,
            savana_change,
        ],
    )
