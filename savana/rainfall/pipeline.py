"""``RainfallAssessment``: the chainable orchestrator tying every
``savana.rainfall`` stage together, mirroring
:class:`savana.pipeline.SavanaClassifier`'s builder pattern.

Every constructor argument is a default that can be overridden — a
different product catalogue, a different gauge network, a different
zone scheme, or different application weights all work the same way
they do calling the individual stage functions directly. This class is
a convenience, not a new capability.
"""

from __future__ import annotations

from . import config


class RainfallAssessment:
    """Chainable orchestrator for a precipitation product assessment.

    Example (defaults — reproduces the WA study)::

        ra = (
            RainfallAssessment()
            .get_observations(source="ee_asset")
            .ingest(start="2001-01-01", end="2020-12-31")
            .extract()
            .assign_zones()
            .validate()
            .score()
        )
        print(ra.summarize())
        ra.export_workbook("decision_tool.xlsx")

    Example (a different station network, subset of products)::

        my_stations = pd.DataFrame({...})
        ra = (
            RainfallAssessment(
                stations_df=my_stations,
                products={"CHIRPS": config.DEFAULT_PRODUCTS["CHIRPS"],
                          "GPM_IMERG": config.DEFAULT_PRODUCTS["GPM_IMERG"]},
            )
            .get_observations(source="download")
            .ingest(start="2015-01-01", end="2023-12-31")
            .extract()
            .validate()   # no assign_zones() call -> pooled validation
            .score()
        )
    """

    def __init__(
        self,
        products: dict | None = None,
        stations_df=None,
        zones_gdf=None,
        zones_fc=None,
        app_weights: dict | None = None,
        zone_notes: dict | None = None,
        rain_threshold: float | None = None,
    ):
        self.products = products if products is not None else config.DEFAULT_PRODUCTS
        self.stations_df = stations_df
        self.zones_gdf = zones_gdf
        self.zones_fc = zones_fc
        self.app_weights = (
            app_weights if app_weights is not None else config.DEFAULT_APP_WEIGHTS
        )
        self.zone_notes = (
            zone_notes if zone_notes is not None else config.DEFAULT_ZONE_NOTES
        )
        self.rain_threshold = (
            rain_threshold
            if rain_threshold is not None
            else config.DEFAULT_RAIN_THRESHOLD_MM_DAY
        )

        # populated as stages run
        self.obs_df = None
        self.products_ic = None
        self.sim_df = None
        self.merged_df = None
        self.validation_by_zone_df = None
        self.validation_overall_df = None
        self.ranking_df = None
        self.threshold_df = None
        self.scores_df = None
        self._facts = None

    # ────────────────────────────────────────────────────
    # Stages
    # ────────────────────────────────────────────────────

    def get_observations(self, source: str = "download", **kwargs):
        from . import stations as _stations

        stations_df = (
            self.stations_df
            if self.stations_df is not None
            else config.default_stations_wa()
        )
        self.stations_df = stations_df
        self.obs_df = _stations.get_observations(stations_df, source=source, **kwargs)
        return self

    def ingest(self, start: str, end: str, roi=None):
        from . import ingestion

        self.start, self.end = start, end
        roi = roi if roi is not None else ingestion.build_roi(self.stations_df)
        self.products_ic = ingestion.load_all_products(
            start, end, roi=roi, products=self.products, stations_df=self.stations_df
        )
        return self

    def extract(self):
        from . import extraction

        if self.products_ic is None:
            raise RuntimeError("Call .ingest() before .extract().")
        self.sim_df = extraction.extract_all_products(
            self.products_ic, self.stations_df
        )
        return self

    def assign_zones(self, zones_gdf=None, zones_fc=None, use_default_if_none=False):
        from . import zones as _zones

        zones_gdf = zones_gdf if zones_gdf is not None else self.zones_gdf
        zones_fc = zones_fc if zones_fc is not None else self.zones_fc
        self.stations_df = _zones.assign_zones(
            self.stations_df,
            zones_gdf=zones_gdf,
            zones_fc=zones_fc,
            use_default_if_none=use_default_if_none,
        )
        return self

    def merge(self):
        from . import extraction

        if self.sim_df is None or self.obs_df is None:
            raise RuntimeError(
                "Call .get_observations() and .extract() before .merge()."
            )
        self.merged_df = extraction.merge_with_observations(
            self.sim_df, self.obs_df, stations_df=self.stations_df
        )
        return self

    def validate(self):
        from . import validation

        if self.merged_df is None:
            self.merge()
        if "zone" in self.merged_df.columns:
            self.validation_by_zone_df = validation.validate_by_zone(
                self.merged_df, threshold=self.rain_threshold
            )
        self.validation_overall_df = validation.validate_overall(
            self.merged_df, threshold=self.rain_threshold
        )
        self.ranking_df = validation.rank_products(
            self.validation_by_zone_df
            if self.validation_by_zone_df is not None
            else self.validation_overall_df
        )
        return self

    def analyze_thresholds(self, thresholds: list[float] | None = None):
        from . import thresholds as _thresholds

        if self.merged_df is None:
            self.merge()
        self.threshold_df = _thresholds.threshold_sensitivity(
            self.merged_df, thresholds
        )
        return self

    def score(self, normalization: str = "fixed"):
        from . import decision

        validation_df = (
            self.validation_by_zone_df
            if self.validation_by_zone_df is not None
            else self.validation_overall_df
        )
        if validation_df is None:
            raise RuntimeError("Call .validate() before .score().")
        self.scores_df = decision.score_products(
            validation_df, weights=self.app_weights, normalization=normalization
        )
        return self

    def run(self, start: str, end: str, obs_source: str = "download", **obs_kwargs):
        """Run every stage end-to-end with sensible defaults."""
        return (
            self.get_observations(source=obs_source, **obs_kwargs)
            .ingest(start=start, end=end)
            .extract()
            .assign_zones()
            .merge()
            .validate()
            .analyze_thresholds()
            .score()
        )

    # ────────────────────────────────────────────────────
    # Insights
    # ────────────────────────────────────────────────────

    def facts(self):
        from . import insights

        if self._facts is None:
            validation_df = (
                self.validation_by_zone_df
                if self.validation_by_zone_df is not None
                else self.validation_overall_df
            )
            if self.scores_df is None or validation_df is None:
                raise RuntimeError("Call .score() before .facts().")
            self._facts = insights.compute_facts(
                self.scores_df,
                validation_df,
                self.ranking_df,
                self.threshold_df,
                zone_notes=self.zone_notes,
            )
        return self._facts

    def summarize(self) -> str:
        from . import insights

        return insights.summarize(self.facts())

    def answer(self, question: str) -> str:
        from . import insights

        return insights.answer(self.facts(), question)

    # ────────────────────────────────────────────────────
    # Outputs
    # ────────────────────────────────────────────────────

    def export_workbook(self, out_path):
        from . import decision

        if self.scores_df is None:
            self.score()
        return decision.build_workbook(
            out_path,
            self.validation_by_zone_df,
            validation_overall_df=self.validation_overall_df,
            ranking_df=self.ranking_df,
            threshold_df=self.threshold_df,
            scores_df=self.scores_df,
            app_weights=self.app_weights,
            zone_notes=self.zone_notes,
        )

    def show(self, kind: str = "recommendation_heatmap", **kwargs):
        from . import viz

        fn = getattr(viz, kind, None)
        if fn is None:
            raise ValueError(f"Unknown figure kind {kind!r}. See savana.rainfall.viz.")
        target_df = (
            self.scores_df
            if "scores_df" in fn.__code__.co_varnames
            else (
                self.validation_by_zone_df
                if self.validation_by_zone_df is not None
                else self.validation_overall_df
            )
        )
        return fn(target_df, **kwargs)
