"""High-level orchestration: the "few lines of code" entry point.

Mirrors the workflow in ``mainrun.js`` step for step, but wrapped as a
single Python object so a Jupyter user can go from an AOI to a
validated, multi-epoch classified savanna land-system map in a handful
of calls instead of hand-assembling every module.

Example
-------
>>> import savana
>>> clf = savana.SavanaClassifier(
...     aoi="projects/ee-desmond/assets/NewParkMerged",
...     name_filter="Kogyae",
...     park_name="Kogyae",
...     epochs=[2017, 2019, 2021, 2024],
... )
>>> clf.run()
>>> clf.maps[2024]                 # ee.Image, classified 2024 land systems
>>> clf.accuracy_summary()         # pandas.DataFrame, one row per model
>>> clf.show(2024)                 # interactive geemap.Map in the notebook
"""

from __future__ import annotations

from . import accuracy as accuracy_mod
from . import change as change_mod
from . import classifiers, composites, config, ee_init
from . import exports as exports_mod
from . import indices
from . import masks as masks_mod
from . import rue as rue_mod
from . import sampling
from . import thresholds as thresholds_mod
from . import viz


class SavanaClassifier:
    """End-to-end adaptive savanna land-system classifier for one AOI.

    All parameters have sane defaults matching the original manuscript
    methodology; override any of them for a different landscape,
    class scheme, or sensor configuration.
    """

    def __init__(
        self,
        aoi,
        name_filter: str | None = None,
        park_name: str = "AOI",
        epochs: list[int] | None = None,
        reference_year: int | None = None,
        class_info: dict | None = None,
        class_property: str = config.CLASS_PROPERTY,
        n_clusters: int = config.DEFAULT_N_CLUSTERS,
        points_per_class: int = config.DEFAULT_POINTS_PER_CLASS,
        candidates_per_cluster: int = config.DEFAULT_CANDIDATES_PER_CLUSTER,
        confidence_margin: float = config.DEFAULT_CONFIDENCE_MARGIN,
        random_seed: int = config.DEFAULT_RANDOM_SEED,
        phenology_min_year: int = config.DEFAULT_PHENOLOGY_MIN_YEAR,
        rf_trees: int = 150,
        scale: int = config.DEFAULT_EXPORT_SCALE,
        crs: str = config.DEFAULT_CRS,
        ee_project: str | None = None,
    ):
        ee_init.initialize(project=ee_project)

        self.region = ee_init.load_aoi(aoi, name_filter=name_filter)
        self.park_name = park_name
        self.epochs = sorted(epochs or [2024])
        self.reference_year = reference_year or self.epochs[-1]
        self.class_info = class_info or config.DEFAULT_CLASS_INFO
        self.class_property = class_property
        self.n_clusters = n_clusters
        self.points_per_class = points_per_class
        self.candidates_per_cluster = candidates_per_cluster
        self.confidence_margin = confidence_margin
        self.random_seed = random_seed
        self.phenology_min_year = phenology_min_year
        self.rf_trees = rf_trees
        self.scale = scale
        self.crs = crs

        # Populated by .run()
        self.idx: dict | None = None
        self.T: dict | None = None
        self.masks: dict | None = None
        self.embedding = None
        self.gcps = None
        self.models: dict | None = None
        self.maps: dict = {}
        self.change: dict | None = None

    # -- pipeline stages, callable individually or via .run() ----------

    def build_features(self):
        """Build composites, indices, RUE, thresholds, and masks for the reference year."""
        s2_annual = composites.sentinel2_annual(self.reference_year, self.region)
        s2_dry = composites.seasonal_composite(
            f"{self.reference_year}-03-01", f"{self.reference_year}-05-15", self.region
        )
        s2_wet = composites.seasonal_composite(
            f"{self.reference_year}-05-01", f"{self.reference_year}-07-15", self.region
        )
        pcts = composites.percentile_composites(self.reference_year, self.region)
        self.embedding = composites.embedding_image(self.reference_year, self.region)

        self.idx = indices.compute(s2_annual, s2_dry, s2_wet, pcts["p10"], pcts["p90"])
        self.rue_annual = rue_mod.compute_annual(self.reference_year, self.region)
        self.T = thresholds_mod.compute(self.idx, self.region)
        self.masks = masks_mod.compute(self.idx, self.T)
        return self

    def sample_training_points(self):
        """Unsupervised clustering + rule-based labelling + class balancing."""
        cluster_result = sampling.cluster_embedding(
            self.embedding,
            self.region,
            n_clusters=self.n_clusters,
            seed=self.random_seed,
        )
        self.gcps = sampling.build_gcps(
            self.embedding,
            self.idx,
            cluster_result["clusters"],
            self.T,
            self.region,
            n_classes=len(self.class_info),
            points_per_class=self.points_per_class,
            scale=self.scale,
            class_property=self.class_property,
            n_clusters=self.n_clusters,
            candidates_per_cluster=self.candidates_per_cluster,
            confidence_margin=self.confidence_margin,
        )
        return self

    def train(self):
        """Train the 4-model ablation + master classifiers."""
        self.models = classifiers.train_all_models(
            self.gcps,
            self.embedding,
            self.idx,
            self.rue_annual["rue"],
            self.region,
            class_property=self.class_property,
            n_trees=self.rf_trees,
            seed=self.random_seed,
            class_order=sorted(self.class_info.keys()),
        )
        return self

    def classify(self):
        """Classify every requested epoch year."""
        self.maps = classifiers.classify_all_epochs(
            self.epochs,
            self.models,
            self.region,
            park_name=self.park_name,
            embedding_current_year=self.reference_year,
            embedding_current_image=self.embedding,
            phenology_min_year=self.phenology_min_year,
        )
        return self

    def analyse_change(self):
        """Run conservative + RUE-validated change detection across epochs."""
        if len(self.epochs) >= 2:
            self.change = change_mod.analyse(
                self.maps, self.epochs, self.region, park_name=self.park_name
            )
        return self

    def run(self):
        """Run the full pipeline: features -> sampling -> training -> classification -> change."""
        return (
            self.build_features()
            .sample_training_points()
            .train()
            .classify()
            .analyse_change()
        )

    # -- results & reporting --------------------------------------------

    def accuracy_summary(self):
        """One row per model (A/B/C/D) with overall accuracy, kappa, PA/UA."""
        matrices = {
            "a": self.models["matrix_a"],
            "b": self.models["matrix_b"],
            "c": self.models["matrix_c"],
            "d": self.models["matrix_d"],
        }
        return accuracy_mod.summary_dataframe(
            matrices, park_name=self.park_name, class_info=self.class_info
        )

    def confusion_matrices(self):
        """Full per-class confusion matrix table across all 4 models."""
        matrices = {
            "a": self.models["matrix_a"],
            "b": self.models["matrix_b"],
            "c": self.models["matrix_c"],
            "d": self.models["matrix_d"],
        }
        return accuracy_mod.confusion_matrix_dataframe(
            matrices, park_name=self.park_name, class_info=self.class_info
        )

    def class_areas(self):
        """Per-epoch class area statistics (km2) as a pandas DataFrame."""
        stats_scale = self.change["stats_scale"] if self.change else self.scale
        return exports_mod.class_areas_dataframe(
            self.maps, self.epochs, self.region, stats_scale
        )

    def export(self, drive_folder: str | None = None, asset_folder: str | None = None):
        """Export classified maps (+ change products, if computed) to Drive/Assets."""
        tasks = exports_mod.export_classified_maps(
            self.maps,
            self.epochs,
            self.region,
            park_name=self.park_name,
            drive_folder=drive_folder,
            asset_folder=asset_folder,
            scale=self.scale,
            crs=self.crs,
        )
        if self.change is not None and (drive_folder or asset_folder):
            tasks += exports_mod.export_change_products(
                self.change,
                self.region,
                park_name=self.park_name,
                drive_folder=drive_folder,
                asset_folder=asset_folder,
                scale=self.scale,
                crs=self.crs,
            )
        return tasks

    def show(self, year: int | None = None, m=None):
        """Display a classified epoch (default: reference year) on an interactive map."""
        year = year or self.reference_year
        return viz.show_classified_map(
            self.maps[year], region=self.region, class_info=self.class_info, m=m
        )

    def show_gcps(self, with_background: bool = True, m=None):
        """Display the ground control points on the map, colored by class.

        A sanity check on the sampling/labelling step — where the
        training points actually landed and whether their classes look
        spatially sensible — before trusting the classifier they train.
        Requires .sample_training_points() (or .run()) to have completed.

        Args:
            with_background: If True (default), shows the reference
                year's classified map underneath the points, dimmed, so
                you can visually compare point placement against the
                result. If False, points are shown alone.
        """
        if self.gcps is None:
            raise RuntimeError("Call .sample_training_points() (or .run()) first.")
        background = None
        if with_background and self.reference_year in self.maps:
            background = self.maps[self.reference_year]
        return viz.show_gcps(
            self.gcps,
            region=self.region,
            class_info=self.class_info,
            class_property=self.class_property,
            background=background,
            m=m,
        )

    def show_years(self, years: list[int] | None = None, m=None):
        """Display several classified epochs as toggleable layers on one map.

        Uses geemap's layer panel — check/uncheck each year's checkbox to
        flip between them. Defaults to all epochs the classifier ran.

        >>> clf.show_years()             # all epochs
        >>> clf.show_years([2019, 2024]) # just these two
        """
        return viz.show_multi_year_map(
            self.maps, years=years, region=self.region, class_info=self.class_info, m=m
        )

    def show_geolibre(self, year: int | None = None, m=None):
        """Display a classified epoch inside the GeoLibre Jupyter widget.

        Alternative to .show() — same idea, different map backend.
        Requires: pip install "savana[geolibre]" (Python >= 3.11).
        """
        from . import viz_geolibre

        year = year or self.reference_year
        return viz_geolibre.show_classified_map(
            self.maps[year], region=self.region, class_info=self.class_info, m=m
        )

    def show_years_geolibre(self, years: list[int] | None = None, m=None):
        """Display several classified epochs as toggleable layers in GeoLibre.

        Alternative to .show_years() — same idea, different map backend.
        Requires: pip install "savana[geolibre]" (Python >= 3.11).
        """
        from . import viz_geolibre

        return viz_geolibre.show_multi_year_map(
            self.maps, years=years, region=self.region, class_info=self.class_info, m=m
        )

    def compare(self, left=2024, right="SATELLITE", m=None):
        """Side-by-side swipe comparison between two years, or a year vs. a basemap.

        ``left``/``right`` each accept either an epoch year (int, must be
        in ``self.maps``) or a basemap name string (e.g. ``"SATELLITE"``,
        ``"HYBRID"``, ``"ROADMAP"``, ``"Esri.WorldImagery"``). Drag the
        handle in the middle of the resulting map to swipe.

        >>> clf.compare(2019, 2024)              # two classified years
        >>> clf.compare(2024, "SATELLITE")        # classified year vs. basemap
        """
        left_img = self.maps[left] if isinstance(left, int) else left
        right_img = self.maps[right] if isinstance(right, int) else right
        left_label = str(left) if isinstance(left, int) else left
        right_label = str(right) if isinstance(right, int) else right
        return viz.compare_split_map(
            left_img,
            right_img,
            left_label=left_label,
            right_label=right_label,
            region=self.region,
            class_info=self.class_info,
            m=m,
        )

    def show_change(self, m=None):
        """Display change-detection layers on an interactive map."""
        if self.change is None:
            raise RuntimeError(
                "Call .analyse_change() (or .run()) with >= 2 epochs first."
            )
        return viz.show_change_map(self.change, region=self.region, m=m)

    def facts(self) -> dict:
        """Compute the grounded facts dict — real numbers from your actual results.

        This is the single source of truth for .summarize() and .answer();
        call it directly if you want the raw structured data instead of text.
        """
        from . import insights

        return insights.compute_facts(self)

    def summarize(self) -> str:
        """Plain-English report generated entirely from real computed results.

        No AI, no invented numbers — every figure here traces back to
        .class_areas() / .accuracy_summary() / the change-detection stats.
        """
        from . import insights

        return insights.summarize(self.facts())

    def answer(self, question: str) -> str:
        """Answer a question about your results using only computed facts.

        Simple keyword matching, not an LLM — it can only ever report
        numbers the pipeline actually produced, so it can't hallucinate.
        Try asking about a class's area, the dominant class, accuracy,
        or change between years.

        >>> clf.answer("how much core woodland is there in 2024?")
        >>> clf.answer("what changed between the years?")
        >>> clf.answer("how accurate is the model?")
        """
        from . import insights

        return insights.answer(self.facts(), question)


def classify_landscape(
    aoi, epochs: list[int] | None = None, park_name: str = "AOI", **kwargs
) -> SavanaClassifier:
    """One-call convenience wrapper: build, run, and return a fitted classifier.

    >>> clf = savana.classify_landscape(
    ...     "path/to/my_park.geojson", epochs=[2020, 2024], park_name="My Park"
    ... )
    >>> clf.show()
    """
    clf = SavanaClassifier(aoi, epochs=epochs, park_name=park_name, **kwargs)
    clf.run()
    return clf
