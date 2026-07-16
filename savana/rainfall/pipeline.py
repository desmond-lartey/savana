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

        ra = (
            RainfallAssessment(
                stations=[(-1.5, 12.4), (2.1, 6.5)],  # or a DataFrame, a
                                                        # .geojson/.csv path,
                                                        # or a single (lon, lat)
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
        stations=None,
        zones_gdf=None,
        zones_fc=None,
        app_weights: dict | None = None,
        zone_notes: dict | None = None,
        rain_threshold: float | None = None,
        cache_dir=None,
        ee_project: str | None = None,
    ):
        from . import stations as _stations

        self.products = products if products is not None else config.DEFAULT_PRODUCTS
        # Accepts anything load_stations_any() accepts: a DataFrame, a
        # .geojson/.csv path, a list of (lon, lat)/(id, lon, lat)/dicts,
        # or a single (lon, lat) tuple/list. Always resolves to a real
        # stations_df immediately (never left as None), defaulting to
        # the WA 16 stations if stations=None.
        self.stations_df = _stations.load_stations_any(stations)
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
        self.cache_dir = cache_dir
        self.ee_project = ee_project

        # populated as stages run
        self.start = None
        self.end = None
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

    def _ensure_ee(self):
        """Initialize Earth Engine with this instance's ``ee_project``,
        called lazily right before any EE-touching operation — not at
        construction time, so a purely offline run (demo/csv
        observations, no ``.ingest()``/``.preview_*`` calls) never
        prompts for EE auth at all. Safe to call repeatedly; a no-op
        after the first successful initialize() in this process (Earth
        Engine's session state is global, not per-object).
        """
        from .. import ee_init

        ee_init.initialize(project=self.ee_project)

    # ────────────────────────────────────────────────────
    # Stages
    # ────────────────────────────────────────────────────

    def get_observations(self, source: str = "download", **kwargs):
        from . import stations as _stations

        if source == "ee_asset":
            self._ensure_ee()

        stations_df = (
            self.stations_df
            if self.stations_df is not None
            else config.default_stations_wa()
        )
        self.stations_df = stations_df

        # If .ingest() already ran and set a date range, and the caller
        # didn't explicitly pass their own start_year/end_year, reuse
        # it -- otherwise "download"/"demo" silently default to the
        # full 2001-2020 range regardless of what .ingest() was told,
        # which is surprising and easy to miss. Only applies to sources
        # that actually take a year range ("csv"/"ee_asset" don't).
        if (
            source in ("download", "demo")
            and "start_year" not in kwargs
            and "end_year" not in kwargs
            and self.start is not None
            and self.end is not None
        ):
            kwargs["start_year"] = int(self.start[:4])
            kwargs["end_year"] = int(self.end[:4])
            print(
                f"  Using date range from .ingest(): "
                f"{kwargs['start_year']}-{kwargs['end_year']} "
                f"(pass start_year=/end_year= explicitly to override)"
            )

        self.obs_df = _stations.get_observations(stations_df, source=source, **kwargs)
        return self

    def ingest(self, start: str, end: str, roi=None):
        from . import ingestion

        self._ensure_ee()
        self.start, self.end = start, end
        roi = roi if roi is not None else ingestion.build_roi(self.stations_df)
        self.products_ic = ingestion.load_all_products(
            start, end, roi=roi, products=self.products, stations_df=self.stations_df
        )
        return self

    def extract(self, cache_dir=None):
        from . import extraction

        if self.products_ic is None:
            raise RuntimeError("Call .ingest() before .extract().")
        self._ensure_ee()
        cache_dir = cache_dir if cache_dir is not None else self.cache_dir
        self.sim_df = extraction.extract_all_products(
            self.products_ic, self.stations_df, cache_dir=cache_dir
        )
        return self

    def assign_zones(self, zones_gdf=None, zones_fc=None, use_default_if_none=False):
        from . import zones as _zones

        zones_gdf = zones_gdf if zones_gdf is not None else self.zones_gdf
        zones_fc = zones_fc if zones_fc is not None else self.zones_fc
        if zones_fc is not None or use_default_if_none:
            self._ensure_ee()
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

    # ────────────────────────────────────────────────────
    # Preview — look before you validate
    # ────────────────────────────────────────────────────

    def preview_stations(self, m=None, zoom: int = 5):
        """Interactive map of station locations. Works as soon as
        stations are set (before ``.get_observations()`` even) — the
        first sanity check: are these actually where you think they are?
        """
        from . import stations as _stations

        self._ensure_ee()
        stations_df = (
            self.stations_df
            if self.stations_df is not None
            else config.default_stations_wa()
        )
        return _stations.preview_map(stations_df, m=m, zoom=zoom)

    def preview_observations(self, station_id: str | None = None):
        """Quick time-series plot of raw GPCC observations. Requires
        ``.get_observations()`` to have run — no product data needed."""
        from . import viz

        if self.obs_df is None:
            raise RuntimeError(
                "Call .get_observations() before .preview_observations()."
            )
        return viz.preview_observations(self.obs_df, station_id=station_id)

    def preview_comparison(
        self, station_id: str | None = None, product: str | None = None
    ):
        """Quick obs-vs-sim scatter, before running formal validation
        metrics. Requires ``.merge()`` (or ``.validate()``, which calls
        it) to have run."""
        from . import viz

        if self.merged_df is None:
            self.merge()
        return viz.preview_comparison(
            self.merged_df, station_id=station_id, product=product
        )

    def preview_map(
        self,
        product: str,
        kind: str = "daily",
        reference: str | None = None,
        show_gpcc: bool = False,
        region=None,
        m=None,
    ):
        """Interactive map of one product's mean rainfall (``kind=
        "daily"`` or ``"annual"``), or its bias against ANOTHER PRODUCT
        if ``reference`` is given — a gridded-vs-gridded comparison,
        never a GPCC comparison (GPCC has no gridded form here).

        Set ``show_gpcc=True`` to overlay real GPCC station values (not
        a rasterized surface — the true point observations, colored on
        the same scale as the raster) on top of the mean map. Requires
        ``.get_observations()`` to have already run. Ignored when
        ``reference`` is also given (the overlay only applies to the
        single-product mean map).

        Requires ``.ingest()`` to have run.
        """
        from . import spatial

        if self.products_ic is None:
            raise RuntimeError("Call .ingest() before .preview_map().")
        if product not in self.products_ic:
            raise ValueError(
                f"Unknown product {product!r}. Ingested: " f"{sorted(self.products_ic)}"
            )
        if region is None:
            from . import ingestion

            region = ingestion.build_roi(self.stations_df)

        if reference is not None:
            if reference not in self.products_ic:
                raise ValueError(
                    f"Unknown reference {reference!r}. Ingested: "
                    f"{sorted(self.products_ic)}"
                )
            return spatial.preview_bias_map(
                self.products_ic[product],
                self.products_ic[reference],
                product_name=product,
                reference_name=reference,
                region=region,
                m=m,
            )

        obs_df, stations_df = None, None
        if show_gpcc:
            if self.obs_df is None:
                raise RuntimeError(
                    "show_gpcc=True requires .get_observations() to " "have run first."
                )
            obs_df, stations_df = self.obs_df, self.stations_df

        return spatial.preview_mean_map(
            self.products_ic[product],
            product_name=product,
            region=region,
            kind=kind,
            m=m,
            obs_df=obs_df,
            stations_df=stations_df,
        )

    def preview_station_bias(self, product: str, m=None, zoom: int = 5):
        """Interactive map of per-station bias against REAL GPCC
        observations for one product — the actual "does this agree with
        ground truth, and where" spatial check. Requires ``.merge()``
        (or ``.validate()``, which calls it) to have run.
        """
        from . import spatial

        if self.merged_df is None:
            self.merge()
        return spatial.preview_station_bias_map(self.merged_df, product, m=m, zoom=zoom)

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


# ════════════════════════════════════════════════════════════
# One-call entry point
# ════════════════════════════════════════════════════════════


def validate_against_gpcc(
    stations=None,
    products: list[str] | None = None,
    start_year: int = 2001,
    end_year: int = 2020,
    obs_source: str | None = None,
    obs_csv=None,
    cache_dir="savana_rainfall_data",
    zones_gdf=None,
    zones_fc=None,
    rain_threshold: float | None = None,
    ee_project: str | None = None,
):
    """Validate one or more precipitation products against GPCC gauge
    observations at one or more stations, over a chosen year range —
    the one-call version of the whole assessment, matching the original
    paper's exact logic (16 WA stations, 6 products, 2001-2020) as the
    default, everything else overridable by simple parameters.

    This is the function to reach for first. It does exactly what the
    original per-station CSV workflow did — extract each requested
    product at each requested station, save/reuse a per-product CSV
    (``cache_dir/precip_extraction_<PRODUCT>.csv``, same as before),
    merge against GPCC observations
    (``cache_dir/gpcc_obs_<start>_<end>.csv``), and write the same
    result CSVs the original scripts did (``validation_by_zone.csv``,
    ``validation_overall.csv``, ``product_ranking.csv``,
    ``threshold_sensitivity.csv``) — just wrapped in one call instead of
    six separate scripts.

    Args:
        stations: where to validate. Any of:
            - ``None`` (default): the 16 WA GPCC stations from the paper.
            - a ``stations_df``, a path to a ``.geojson``/``.csv`` file
              of station points, a list of ``(lon, lat)`` tuples, or a
              single ``(lon, lat)`` tuple — see
              :func:`savana.rainfall.stations.load_stations_any` for
              the full list of accepted shapes. Works the same whether
              you give it 1 station or 100.
        products: which products to check, by name (e.g.
            ``["CHIRPS", "GPM_IMERG"]``). ``None`` (default) uses all 6
            in :data:`config.DEFAULT_PRODUCTS`. Any subset works.
        start_year, end_year: inclusive year range (plain ints — the
            paper used 2001-2020; pick whatever you need).
        obs_source: where GPCC observations come from —
            ``"ee_asset"`` (fast, only covers the 16 WA stations),
            ``"download"`` (slower, works for any station anywhere),
            ``"csv"`` (use ``obs_csv=`` — you already have one), or
            ``"demo"`` (synthetic, testing only). Defaults to
            ``"ee_asset"`` when ``stations`` is the WA default (fastest
            path for the paper's own network) and ``"download"``
            otherwise (since the EE asset only has the WA 16).
        obs_csv: required if ``obs_source="csv"``.
        cache_dir: where per-product extraction CSVs, the GPCC obs CSV,
            and the result CSVs are read from / written to. Sits right
            next to your notebook by default; set to ``None`` to skip
            all file caching and keep everything in memory only.
        zones_gdf, zones_fc: optional zone geometry (see
            :mod:`savana.rainfall.zones`) for zone-stratified results.
            Omit for pooled (unzoned) validation.
        rain_threshold: mm/day wet/dry threshold for categorical
            metrics. Defaults to the WMO standard (1.0 mm/day).
        ee_project: Google Cloud project registered for Earth Engine use
            (only needed for ``obs_source="ee_asset"`` or the default
            Earth Engine ingestion — not needed at all if you only use
            ``obs_source="csv"``/``"demo"``). If omitted, uses whatever
            is already configured for the environment (see
            ``savana.ee_init.initialize``) — set this explicitly if
            you have more than one Google Cloud project and the wrong
            one keeps getting picked up.

    Returns:
        A fully populated :class:`RainfallAssessment` — inspect
        ``.validation_by_zone_df`` / ``.validation_overall_df``
        directly, or call ``.summarize()``, ``.answer("...")``,
        ``.show()``, ``.export_workbook(...)`` on it, same as building
        one by hand.

    Example::

        from savana.rainfall import validate_against_gpcc

        # Reproduce the paper exactly:
        result = validate_against_gpcc()

        # One station, two products, a shorter recent period:
        result = validate_against_gpcc(
            stations=(-1.5, 12.4),
            products=["CHIRPS", "GPM_IMERG"],
            start_year=2018, end_year=2023,
        )
        print(result.validation_overall_df)
    """
    from pathlib import Path

    from . import stations as _stations

    stations_df = _stations.load_stations_any(stations)
    is_default_wa_network = stations is None

    if products is None:
        selected_products = config.DEFAULT_PRODUCTS
    else:
        unknown = [p for p in products if p not in config.DEFAULT_PRODUCTS]
        if unknown:
            raise ValueError(
                f"Unknown product(s) {unknown}. Known products: "
                f"{sorted(config.DEFAULT_PRODUCTS)}."
            )
        selected_products = {p: config.DEFAULT_PRODUCTS[p] for p in products}

    if obs_source is None:
        obs_source = "ee_asset" if is_default_wa_network else "download"

    cache_path = Path(cache_dir) if cache_dir else None

    ra = RainfallAssessment(
        products=selected_products,
        stations=stations_df,
        zones_gdf=zones_gdf,
        zones_fc=zones_fc,
        rain_threshold=rain_threshold,
        cache_dir=cache_path,
        ee_project=ee_project,
    )

    obs_kwargs = {}
    if obs_source == "csv":
        if obs_csv is None:
            raise ValueError('obs_source="csv" requires obs_csv=<path>.')
        obs_kwargs = {"obs_csv": obs_csv}
    elif obs_source == "download":
        obs_kwargs = {"start_year": start_year, "end_year": end_year}
        if cache_path:
            obs_kwargs["data_dir"] = cache_path
    elif obs_source == "demo":
        obs_kwargs = {"start_year": start_year, "end_year": end_year}
    # "ee_asset" takes no year kwargs — filtered to the requested range below instead

    ra.get_observations(source=obs_source, **obs_kwargs)
    ra.obs_df = ra.obs_df[
        (ra.obs_df["year"] >= start_year) & (ra.obs_df["year"] <= end_year)
    ].reset_index(drop=True)
    if ra.obs_df.empty:
        raise ValueError(
            f"No GPCC observations found for {start_year}-{end_year} with "
            f"obs_source={obs_source!r}. Check the year range against what "
            f"that source actually covers."
        )
    ra.ingest(start=f"{start_year}-01-01", end=f"{end_year}-12-31")
    ra.extract(cache_dir=cache_path)
    if zones_gdf is not None or zones_fc is not None:
        ra.assign_zones()
    ra.merge()
    ra.validate()
    ra.analyze_thresholds()
    ra.score()

    if cache_path:
        cache_path.mkdir(parents=True, exist_ok=True)
        ra.merged_df.to_csv(
            cache_path
            / (
                "merged_obs_grid_zoned.csv"
                if "zone" in ra.merged_df.columns
                else "merged_obs_grid.csv"
            ),
            index=False,
        )
        if ra.validation_by_zone_df is not None:
            ra.validation_by_zone_df.to_csv(
                cache_path / "validation_by_zone.csv", index=False
            )
        ra.validation_overall_df.to_csv(
            cache_path / "validation_overall.csv", index=False
        )
        ra.ranking_df.to_csv(cache_path / "product_ranking.csv", index=False)
        ra.threshold_df.to_csv(cache_path / "threshold_sensitivity.csv", index=False)
        print(f"  Result CSVs written to: {cache_path}")

    return ra
