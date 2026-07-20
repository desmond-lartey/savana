"""Confusion matrix and accuracy summary reporting.

Ports the CSV structure from ``accuracy.js`` (24-row full confusion
matrix across 4 models x 6 classes, plus a 4-row per-model summary),
but returns ``pandas.DataFrame`` directly for notebook use, Drive/CSV
export is available separately via :mod:`savana.exports`.
"""

from __future__ import annotations

from . import config

MODEL_LABELS = {
    "a": (
        "A_KNN3_Embeddings",
        "KNN (k=3) | AlphaEarth Embeddings only",
        "Embeddings [baseline]",
    ),
    "b": ("B_RF_Embeddings", "RF | AlphaEarth Embeddings only", "Embeddings"),
    "c": (
        "C_RF_PhenologyOnly",
        "RF | Phenological Indices only [CIRCULAR]",
        "Phenology only \u2014 circularity inflates OA",
    ),
    "d": (
        "D_RF_Embeddings_Pheno",
        "RF | Embeddings + Phenology [PRIMARY]",
        "Embeddings + Phenology",
    ),
}


def _class_labels(class_info: dict) -> list[tuple[int, str]]:
    return [
        (code, info["name"].replace(" ", "_").replace("/", "").replace("__", "_"))
        for code, info in sorted(class_info.items())
    ]


def confusion_matrix_dataframe(
    matrices: dict, park_name: str = "AOI", class_info: dict | None = None
):
    """Build the full 24-row (4 models x N classes) confusion matrix table.

    ``matrices`` maps model key ("a","b","c","d") to an ``ee.ConfusionMatrix``.
    """
    import pandas as pd

    info = class_info or config.DEFAULT_CLASS_INFO
    classes = _class_labels(info)

    rows = []
    for key, cm in matrices.items():
        model_name, _, _ = MODEL_LABELS.get(key, (key, key, key))
        oa = cm.accuracy().getInfo()
        kappa = cm.kappa().getInfo()
        pa = cm.producersAccuracy().getInfo()
        ua = cm.consumersAccuracy().getInfo()
        arr = cm.array().getInfo()
        for i, (code, label) in enumerate(classes):
            row = {
                "park": park_name,
                "model": model_name,
                "actual_class_code": code,
                "actual_class_label": label,
                "overall_accuracy": oa,
                "kappa": kappa,
                "producer_accuracy": pa[i][0] if i < len(pa) else None,
                "user_accuracy": ua[0][i] if i < len(ua[0]) else None,
            }
            for j, (_, pred_label) in enumerate(classes):
                row[f"pred_{pred_label}"] = (
                    arr[i][j] if i < len(arr) and j < len(arr[i]) else None
                )
            rows.append(row)
    return pd.DataFrame(rows)


def summary_dataframe(
    matrices: dict, park_name: str = "AOI", class_info: dict | None = None
):
    """One row per model with overall accuracy, kappa, and per-class PA/UA."""
    import pandas as pd

    info = class_info or config.DEFAULT_CLASS_INFO
    classes = _class_labels(info)

    rows = []
    for key, cm in matrices.items():
        model_code, model_desc, feature_space = MODEL_LABELS.get(key, (key, key, key))
        oa = cm.accuracy().getInfo()
        kappa = cm.kappa().getInfo()
        pa = cm.producersAccuracy().getInfo()
        ua = cm.consumersAccuracy().getInfo()
        row = {
            "park": park_name,
            "model_code": key.upper(),
            "model_description": model_desc,
            "feature_space": feature_space,
            "overall_accuracy": oa,
            "kappa": kappa,
        }
        for i, (_, label) in enumerate(classes):
            row[f"PA_{label}"] = pa[i][0] if i < len(pa) else None
            row[f"UA_{label}"] = ua[0][i] if i < len(ua[0]) else None
        rows.append(row)
    return pd.DataFrame(rows)


def print_summary(matrices: dict, park_name: str = "AOI") -> None:
    """Console summary mirroring the ablation-comparison prints in kogyai.js."""
    print(f"--- ACCURACY: {park_name} ---")
    for key in ["a", "b", "c", "d"]:
        if key not in matrices:
            continue
        cm = matrices[key]
        note = " [CIRCULAR, inflated, diagnostic only]" if key == "c" else ""
        oa = cm.accuracy().getInfo()
        kappa = cm.kappa().getInfo()
        print(f"Model {key.upper()} | OA: {oa:.4f} | Kappa: {kappa:.4f}{note}")
    print("")
    print("Interpretation guide:")
    print("  B > A  -> RF outperforms KNN on the same embeddings")
    print("  D > B  -> phenology adds value beyond embeddings alone")
    print("  D > C  -> embeddings add value beyond indices alone")
    print("  C is circular (labels derived from the same indices), diagnostic only")
    print("  Model D (primary) is used for all epoch mapping.")
