"""GCP (ground control point) generation.

Unsupervised clustering -> cluster-stratified candidate sampling ->
rule-based provisional labelling with a confidence-margin filter ->
class balancing -> embedding extraction. Direct port of ``sampling.js``
(and the equivalent Phase 4 logic in ``kogyae.js``).
"""

from __future__ import annotations

from . import config


def cluster_embedding(
    embedding,
    region,
    n_clusters: int = config.DEFAULT_N_CLUSTERS,
    seed: int = config.DEFAULT_RANDOM_SEED,
):
    """Unsupervised k-means clustering in AlphaEarth embedding space.

    Returns ``{"clusters": image, "samples": feature_collection}``.
    """
    import ee

    samples = embedding.sample(
        region=region, scale=30, numPixels=3000, seed=seed, tileScale=8
    )
    kmeans = ee.Clusterer.wekaKMeans(nClusters=n_clusters, seed=seed).train(samples)
    clusters = embedding.cluster(kmeans).toInt().rename("cluster6")
    return {"clusters": clusters, "samples": samples}


def sample_candidates(
    idx: dict,
    clusters,
    region,
    n_clusters: int = config.DEFAULT_N_CLUSTERS,
    candidates_per_cluster: int = config.DEFAULT_CANDIDATES_PER_CLUSTER,
    scale: int = config.DEFAULT_EXPORT_SCALE,
):
    """Cluster-stratified candidate point sampling."""
    import ee

    candidate_image = ee.Image.cat(
        [
            idx["ndvi"],
            idx["ndmi"],
            idx["mndwi"],
            idx["ndbi"],
            idx["ndvi_dry"],
            idx["ndmi_dry"],
            idx["ndbi_dry"],
            idx["ndvi_wet"],
            idx["ndmi_wet"],
            idx["ndvi_amp"],
            clusters,
        ]
    ).clip(region)

    keep_props = [
        "cluster6",
        "NDVI",
        "NDMI",
        "NDBI",
        "NDVI_dry",
        "NDMI_dry",
        "NDBI_dry",
        "NDVI_wet",
        "NDMI_wet",
        "NDVI_amp",
    ]

    def sample_cluster(cluster_id, seed):
        return (
            candidate_image.updateMask(clusters.eq(cluster_id))
            .sample(
                region=region,
                scale=scale,
                numPixels=candidates_per_cluster * 10,
                seed=seed,
                geometries=True,
                tileScale=8,
            )
            .filter(
                ee.Filter.notNull(
                    [
                        "cluster6",
                        "NDVI",
                        "NDMI",
                        "NDBI",
                        "NDVI_dry",
                        "NDMI_dry",
                        "NDVI_wet",
                        "NDMI_wet",
                    ]
                )
            )
            .randomColumn("pick", seed)
            .sort("pick")
            .limit(candidates_per_cluster)
            .map(lambda f: ee.Feature(f.geometry(), {p: f.get(p) for p in keep_props}))
        )

    seeds = [100 + 10 * i for i in range(n_clusters)]
    candidates = ee.FeatureCollection(
        [sample_cluster(i, seeds[i]) for i in range(n_clusters)]
    ).flatten()
    return candidates


def assign_labels(
    candidates,
    T: dict,
    confidence_margin: float = config.DEFAULT_CONFIDENCE_MARGIN,
    class_property: str = config.CLASS_PROPERTY,
):
    """Assign rule-based provisional labels; filter out low-confidence and invalid points.

    Returns the filtered, valid-labelled ``ee.FeatureCollection``.
    """
    import ee

    def _label(f):
        ndvi_v = ee.Number(f.get("NDVI"))
        ndmi_v = ee.Number(f.get("NDMI"))
        ndbi_v = ee.Number(f.get("NDBI"))
        ndvi_dry = ee.Number(f.get("NDVI_dry"))
        ndmi_dry = ee.Number(f.get("NDMI_dry"))
        ndvi_amp = ee.Number(ee.Algorithms.If(f.get("NDVI_amp"), f.get("NDVI_amp"), 0))

        is_ambiguous = (
            ndvi_dry.gt(T["CORE_NDVI_DRY"].subtract(confidence_margin))
            .And(ndvi_dry.lt(T["CORE_NDVI_DRY"].add(confidence_margin)))
            .Or(
                ndvi_dry.gt(T["GRASS_NDVI_DRY_MAX"].subtract(confidence_margin)).And(
                    ndvi_dry.lt(T["GRASS_NDVI_DRY_MAX"].add(confidence_margin))
                )
            )
            .Or(
                ndvi_dry.gt(T["OPEN_NDVI_DRY_MIN"].subtract(confidence_margin)).And(
                    ndvi_dry.lt(T["OPEN_NDVI_DRY_MIN"].add(confidence_margin))
                )
            )
        )

        label = ee.Number(
            ee.Algorithms.If(
                ndbi_v.gt(T["ANTHRO_NDBI"]).Or(ndvi_v.lt(T["ANTHRO_NDVI_MAX"])),
                6,
                ee.Algorithms.If(
                    ndmi_v.gt(T["RIPARIAN_NDMI"])
                    .And(ndmi_dry.gt(T["RIPARIAN_NDMI_DRY"]))
                    .And(ndvi_dry.gt(T["RIPARIAN_NDVI_DRY"])),
                    5,
                    ee.Algorithms.If(
                        ndvi_dry.gt(T["CORE_NDVI_DRY"]).And(ndmi_v.gt(T["CORE_NDMI"])),
                        1,
                        ee.Algorithms.If(
                            ndvi_dry.lt(T["GRASS_NDVI_DRY_MAX"]).And(
                                ndvi_amp.gt(T["GRASS_AMP_MIN"]).Or(
                                    ndmi_dry.lt(T["GRASS_NDMI_DRY_MAX"])
                                )
                            ),
                            4,
                            ee.Algorithms.If(
                                ndvi_dry.gte(T["SHRUB_NDVI_DRY_MIN"])
                                .And(ndvi_dry.lt(T["SHRUB_NDVI_DRY_MAX"]))
                                .And(ndmi_dry.gte(T["SHRUB_NDMI_DRY_MIN"]))
                                .And(ndmi_dry.lt(T["SHRUB_NDMI_DRY_MAX"]))
                                .And(ndvi_amp.gte(T["SHRUB_AMP_MIN"]))
                                .And(ndvi_amp.lt(T["SHRUB_AMP_MAX"])),
                                3,
                                ee.Algorithms.If(
                                    ndvi_dry.gte(T["OPEN_NDVI_DRY_MIN"])
                                    .And(ndvi_dry.lte(T["OPEN_NDVI_DRY_MAX"]))
                                    .And(ndmi_v.gte(T["OPEN_NDMI_MIN"]))
                                    .And(ndmi_v.lte(T["OPEN_NDMI_MAX"])),
                                    2,
                                    -1,
                                ),
                            ),
                        ),
                    ),
                ),
            )
        )

        is_rare = label.eq(3).Or(label.eq(5))
        final_label = ee.Number(
            ee.Algorithms.If(is_rare, label, ee.Algorithms.If(is_ambiguous, 99, label))
        )
        return f.set(class_property, final_label)

    labelled = candidates.map(_label)
    valid = labelled.filter(ee.Filter.gt(class_property, 0)).filter(
        ee.Filter.neq(class_property, 99)
    )
    return valid


def build_gcps(
    embedding,
    idx: dict,
    clusters,
    T: dict,
    region,
    n_classes: int = 6,
    points_per_class: int = config.DEFAULT_POINTS_PER_CLASS,
    scale: int = config.DEFAULT_EXPORT_SCALE,
    class_property: str = config.CLASS_PROPERTY,
    n_clusters: int = config.DEFAULT_N_CLUSTERS,
    candidates_per_cluster: int = config.DEFAULT_CANDIDATES_PER_CLUSTER,
    confidence_margin: float = config.DEFAULT_CONFIDENCE_MARGIN,
):
    """End-to-end: sample candidates -> label -> balance -> extract embeddings.

    Returns the final ``ee.FeatureCollection`` of ground control points
    with embedding bands attached, ready for classifier training.
    """
    import ee

    candidates = sample_candidates(
        idx,
        clusters,
        region,
        n_clusters=n_clusters,
        candidates_per_cluster=candidates_per_cluster,
        scale=scale,
    )
    labelled = assign_labels(
        candidates,
        T,
        confidence_margin=confidence_margin,
        class_property=class_property,
    )

    def take(fc, class_val, seed):
        sub = fc.filter(ee.Filter.eq(class_property, class_val))
        return ee.FeatureCollection(
            ee.Algorithms.If(
                sub.size().gte(points_per_class),
                sub.randomColumn("pick", seed).sort("pick").limit(points_per_class),
                sub,
            )
        )

    balanced = None
    for i, class_val in enumerate(range(1, n_classes + 1)):
        chunk = take(labelled, class_val, 101 + i)
        balanced = chunk if balanced is None else balanced.merge(chunk)

    gcps = embedding.sampleRegions(
        collection=balanced.filterBounds(region),
        properties=[
            class_property,
            "cluster6",
            "NDVI",
            "NDMI",
            "NDBI",
            "NDVI_dry",
            "NDMI_dry",
            "NDVI_wet",
            "NDMI_wet",
            "NDVI_amp",
        ],
        scale=scale,
        geometries=True,
        tileScale=8,
    ).filter(ee.Filter.notNull(embedding.bandNames()))

    return gcps
