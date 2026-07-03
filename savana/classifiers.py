"""Four-model ablation training and multi-epoch classification.

Ported from ``kogyae.js`` Phase 5 (training), Phase 7 (accuracy split),
and Phase 8 (multi-epoch classification) — the standalone
``classifers.js`` module referenced by ``mainrun.js`` was empty, so this
reconstructs it with the exact signatures ``mainrun.js`` expects
(``trainAllModels``, ``classifyAllEpochs``).

Models:
    A: KNN (k=3)              | AlphaEarth embeddings only [baseline]
    B: Random Forest          | AlphaEarth embeddings only
    C: Random Forest          | Phenology indices only [CIRCULAR — ablation only,
                                 not used operationally, since labels were
                                 derived from the same indices]
    D: Random Forest          | Embeddings + Phenology [PRIMARY — used for mapping]
"""

from __future__ import annotations

from . import composites, config, indices, rue as rue_mod


def train_all_models(
    gcps,
    embedding,
    idx: dict,
    rue_img,
    region,
    class_property: str = config.CLASS_PROPERTY,
    n_trees: int = 150,
    split_fraction: float = 0.7,
    seed: int = config.DEFAULT_RANDOM_SEED,
    class_order: list[int] | None = None,
) -> dict:
    """Train the 4-model ablation and the two "master" classifiers used
    for mapping (Model B for years without reliable phenology, Model D
    for all other years).

    Returns a dict with the trained classifiers, error matrices, and
    the exact band lists each classifier expects (so downstream
    classification always matches training feature order).
    """
    import ee

    class_order = class_order or [1, 2, 3, 4, 5, 6]

    training_data = embedding.sampleRegions(
        collection=gcps, properties=[class_property], scale=config.DEFAULT_EXPORT_SCALE, tileScale=8
    ).filter(ee.Filter.notNull(embedding.bandNames()))

    with_random = gcps.randomColumn("split", seed)
    train_set = with_random.filter(ee.Filter.lt("split", split_fraction))
    valid_set = with_random.filter(ee.Filter.gte("split", split_fraction))

    pheno_stack = indices.build_pheno_stack(idx, rue_img)
    pheno_bands = pheno_stack.bandNames()
    combined_stack = ee.Image.cat([embedding, pheno_stack])
    combined_bands = combined_stack.bandNames()

    train_full = combined_stack.sampleRegions(
        collection=train_set, properties=[class_property], scale=config.DEFAULT_EXPORT_SCALE, tileScale=8
    ).filter(ee.Filter.notNull(combined_bands))
    valid_full = combined_stack.sampleRegions(
        collection=valid_set, properties=[class_property], scale=config.DEFAULT_EXPORT_SCALE, tileScale=8
    ).filter(ee.Filter.notNull(combined_bands))

    emb_bands = embedding.bandNames()
    class_prop_list = ee.List([class_property])
    train_emb = train_full.select(emb_bands.cat(class_prop_list))
    valid_emb = valid_full.select(emb_bands.cat(class_prop_list))
    train_pheno = train_full.select(pheno_bands.cat(class_prop_list))
    valid_pheno = valid_full.select(pheno_bands.cat(class_prop_list))

    # Model A — KNN (k=3) | Embeddings only [baseline]
    model_a = ee.Classifier.smileKNN(3).train(
        features=train_emb, classProperty=class_property, inputProperties=emb_bands
    )
    matrix_a = valid_emb.classify(model_a).errorMatrix(
        actual=class_property, predicted="classification", order=class_order
    )

    # Model B — RF (150 trees) | Embeddings only
    model_b = ee.Classifier.smileRandomForest(
        numberOfTrees=n_trees, variablesPerSplit=8, minLeafPopulation=1, bagFraction=0.632, seed=seed
    ).train(features=train_emb, classProperty=class_property, inputProperties=emb_bands)
    matrix_b = valid_emb.classify(model_b).errorMatrix(
        actual=class_property, predicted="classification", order=class_order
    )

    # Model C — RF (150 trees) | Phenology only [CIRCULAR — ablation diagnostic only]
    model_c = ee.Classifier.smileRandomForest(
        numberOfTrees=n_trees, variablesPerSplit=4, minLeafPopulation=1, bagFraction=0.632, seed=seed
    ).train(features=train_pheno, classProperty=class_property, inputProperties=pheno_bands)
    matrix_c = valid_pheno.classify(model_c).errorMatrix(
        actual=class_property, predicted="classification", order=class_order
    )

    # Model D — RF (150 trees) | Embeddings + Phenology [PRIMARY]
    model_d = ee.Classifier.smileRandomForest(
        numberOfTrees=n_trees, variablesPerSplit=9, minLeafPopulation=1, bagFraction=0.632, seed=seed
    ).train(features=train_full, classProperty=class_property, inputProperties=combined_bands)
    matrix_d = valid_full.classify(model_d).errorMatrix(
        actual=class_property, predicted="classification", order=class_order
    )

    # "Master" classifiers used for actual epoch mapping, trained on the
    # FULL gcps/trainFull sets (not just the 70% split) for best final quality.
    master_b = ee.Classifier.smileRandomForest(
        numberOfTrees=n_trees, variablesPerSplit=8, minLeafPopulation=1, bagFraction=0.632, seed=seed
    ).train(features=training_data, classProperty=class_property, inputProperties=embedding.bandNames())

    model_d_band_names = embedding.bandNames().cat(ee.List(indices.PHENO_BAND_ORDER))
    master_d = ee.Classifier.smileRandomForest(
        numberOfTrees=n_trees, variablesPerSplit=9, minLeafPopulation=1, bagFraction=0.632, seed=seed
    ).train(features=train_full, classProperty=class_property, inputProperties=model_d_band_names)

    return {
        "model_a": model_a, "matrix_a": matrix_a,
        "model_b": model_b, "matrix_b": matrix_b,
        "model_c": model_c, "matrix_c": matrix_c,
        "model_d": model_d, "matrix_d": matrix_d,
        "master_b": master_b,
        "master_d": master_d,
        "embedding_bands": embedding.bandNames(),
        "model_d_band_names": model_d_band_names,
        "class_property": class_property,
    }


def classify_all_epochs(
    epochs: list[int],
    models: dict,
    region,
    park_name: str = "AOI",
    embedding_current_year: int | None = None,
    embedding_current_image=None,
    phenology_min_year: int = config.DEFAULT_PHENOLOGY_MIN_YEAR,
    smooth_radius_px: int = 1,
) -> dict:
    """Classify every epoch year with the appropriate master classifier.

    Years >= ``phenology_min_year`` use Model D (embeddings + phenology,
    recomputed for that specific year). Earlier years — where seasonal
    Sentinel-2 coverage is typically too sparse for reliable phenology
    — fall back to Model B (embeddings only). This generalises the
    hardcoded "if year === 2017" special case in the original script.

    ``embedding_current_year``/``embedding_current_image``: if one of
    the epochs is the same year the embedding used for training was
    already computed for, pass it in to avoid recomputing it.

    Returns ``{year: classified_image}``.
    """
    import ee

    class_property = models["class_property"]
    classified_maps = {}

    for year in epochs:
        if embedding_current_year is not None and year == embedding_current_year:
            emb_img = embedding_current_image
        else:
            emb_img = composites.embedding_image(year, region)

        if year < phenology_min_year:
            classified = (
                emb_img.classify(models["master_b"])
                .rename(class_property)
                .clip(region)
                .toByte()
                .focal_mode(radius=smooth_radius_px, units="pixels", kernelType="square")
                .rename(class_property)
                .clip(region)
                .toByte()
                .set("year", year)
                .set("park", park_name)
                .set("classifier", "ModelB_RF_Embeddings")
                .set("system:time_start", ee.Date.fromYMD(year, 1, 1).millis())
            )
        else:
            yr = str(year)
            s2_annual_yr = composites.sentinel2_annual(year, region)
            s2_dry_yr = composites.seasonal_composite(f"{yr}-03-01", f"{yr}-05-15", region)
            s2_wet_yr = composites.seasonal_composite(f"{yr}-05-01", f"{yr}-07-15", region)
            pcts_yr = composites.percentile_composites(year, region)

            idx_yr = indices.compute(s2_annual_yr, s2_dry_yr, s2_wet_yr, pcts_yr["p10"], pcts_yr["p90"])
            idx_yr = {k: v.unmask(0) for k, v in idx_yr.items()}
            rue_yr = rue_mod.epoch_rue(year, region).select([f"RUE_{yr}"]).rename("RUE")

            pheno_stack_yr = indices.build_pheno_stack(idx_yr, rue_yr)
            combined_img_yr = ee.Image.cat([emb_img, pheno_stack_yr])

            classified = (
                combined_img_yr.classify(models["master_d"])
                .rename(class_property)
                .clip(region)
                .toByte()
                .focal_mode(radius=smooth_radius_px, units="pixels", kernelType="square")
                .rename(class_property)
                .clip(region)
                .toByte()
                .set("year", year)
                .set("park", park_name)
                .set("classifier", "ModelD_RF_Embeddings_Phenology")
                .set("system:time_start", ee.Date.fromYMD(year, 1, 1).millis())
            )

        classified_maps[year] = classified

    return classified_maps
