"""A savana-native agent, built directly on Strands (same engine geoai's
GeoAgent uses), rather than through the standalone GeoAgent package.

This exists alongside :mod:`savana.agent` (the ``for_savana()`` factory,
built on the standalone ``GeoAgent`` package) rather than replacing it —
both work, but this module talks to Strands directly, which avoids the
``max_tokens`` bug in the standalone package's Anthropic path, and gives
a foundation to grow the same way geoai's agent did: starting with
grounded Q&A tools (what's here now), with map-control tools as a
natural, separate next addition (see the module docstring note at the
bottom for scope).

Requires: ``pip install "savana[agents]"``.

Example
-------
>>> import savana
>>> from savana.agents import SavanaGeoAgent
>>>
>>> clf = savana.classify_landscape(aoi=..., epochs=[2019, 2024], park_name="Kyabobo")
>>> agent = SavanaGeoAgent(clf, model="claude-sonnet-4-6")
>>> print(agent.ask("How much core woodland is there in 2024?"))
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
    supplies one) is deliberate — omitting it is what causes a bare
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


class SavanaTools:
    """Grounded savana query tools, bound to one fitted SavanaClassifier.

    Same design principle as :mod:`savana.insights`: every tool here can
    only report numbers actually computed by the pipeline. Results are
    cached after the first call in a session — see ``refresh()``.
    """

    def __init__(self, clf):
        self.clf = clf
        self._facts_cache: Optional[dict] = None

    def _facts(self, force_refresh: bool = False) -> dict:
        from . import insights

        if force_refresh or self._facts_cache is None:
            self._facts_cache = insights.compute_facts(self.clf)
        return self._facts_cache

    def _tool_methods(self) -> list:
        """Return the bound, @tool-decorated methods for Agent(tools=[...])."""
        return [
            self.summarize,
            self.class_area,
            self.dominant_class,
            self.accuracy,
            self.change,
            self.refresh,
        ]

    def _make_tools(self):
        from strands import tool

        from . import insights

        # Bound as closures over `self` so each tool call reads/writes the
        # same cache, while still being registerable as standalone @tool
        # functions (Strands inspects each function's own signature/docstring).

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


DEFAULT_SYSTEM_PROMPT = """You are a geospatial analysis assistant for the savana package,
which classifies savanna landscapes into land-system management classes
(Core Woodland, Open Woodland, Shrub-Transition Savanna, Grassland,
Riparian/Wetland Vegetation, Anthropogenic Disturbance).

Answer questions ONLY using the savana_* tools available to you — never
estimate or guess an area, percentage, or accuracy figure yourself.
If a tool doesn't have the information needed to answer, say so plainly
rather than inventing a plausible-sounding number."""


class SavanaGeoAgent:
    """A savana-native agent bound to a fitted SavanaClassifier's real results.

    Built directly on Strands (the same engine geoai's own GeoAgent uses),
    not through the standalone GeoAgent package — this avoids that
    package's ``max_tokens`` bug and gives a foundation savana can extend
    on its own terms (e.g. adding map-control tools later, the same way
    geoai's GeoAgent grew from Q&A into full map control).

    Args:
        clf: A ``SavanaClassifier`` that has already run.
        model: Either a provider name (``"anthropic"``, ``"openai"``,
            ``"gemini"`` — uses that provider's env-var API key and a
            sensible default model id) or an already-built Strands model
            instance for full control.
        model_id: Optional explicit model id, used only when ``model`` is
            a provider name string.
        system_prompt: Overrides the default savana-scoped system prompt.
        **model_kwargs: Passed through to the model factory (e.g.
            ``api_key=``, ``max_tokens=``).
    """

    def __init__(
        self,
        clf,
        model: str = "anthropic",
        model_id: Optional[str] = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        **model_kwargs: Any,
    ):
        _require_strands()
        from strands import Agent

        self.tools = SavanaTools(clf)

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
            tools=self.tools._make_tools(),
        )

    def ask(self, prompt: str) -> str:
        """Send a single-turn question, get a plain-text answer back."""
        result = self._agent(prompt)
        return getattr(result, "final_text", str(result))

    def __call__(self, prompt: str):
        """Full Strands result object (same as calling the agent directly)."""
        return self._agent(prompt)


# --- Scope note for future work -------------------------------------------
# geoai's GeoAgent grew from a Q&A-only tool set into full interactive map
# control (fly_to, add_basemap, add_vector, etc., see geoai.agents.map_tools)
# plus a rich show_ui() split map+chat panel. The natural next additions
# here, in the same spirit but scoped to savana's own domain, would be:
#   1. Map-control tools bound to a geemap.Map (savana already depends on
#      geemap for .show()/.show_years()), so the agent could add/toggle
#      classified-year layers, fly to the AOI, etc. — not just answer
#      questions about them.
#   2. A show_ui() widget combining a live geemap.Map panel with the chat
#      box from savana.agent.chat_widget().
# Neither is built yet — this module intentionally ships the grounded-Q&A
# foundation first, verified working, rather than a larger unverified whole.
