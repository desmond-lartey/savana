"""Spectral index computation and the 14-band phenological stack.

Direct port of ``indices.js``.
"""

from __future__ import annotations


def compute(s2_annual, s2_dry, s2_wet, p10, p90) -> dict:
    """Compute all spectral indices from seasonal/percentile composites.

    Returns a dict, access as ``idx["ndvi"]``, ``idx["ndvi_dry"]``, etc.
    """
    ndvi = s2_annual.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndmi = s2_annual.normalizedDifference(["B8", "B11"]).rename("NDMI")
    mndwi = s2_annual.normalizedDifference(["B3", "B11"]).rename("MNDWI")
    ndbi = s2_annual.normalizedDifference(["B11", "B8"]).rename("NDBI")
    ndvi_dry = s2_dry.normalizedDifference(["B8", "B4"]).rename("NDVI_dry")
    ndmi_dry = s2_dry.normalizedDifference(["B8", "B11"]).rename("NDMI_dry")
    ndbi_dry = s2_dry.normalizedDifference(["B11", "B8"]).rename("NDBI_dry")
    ndvi_wet = s2_wet.normalizedDifference(["B8", "B4"]).rename("NDVI_wet")
    ndmi_wet = s2_wet.normalizedDifference(["B8", "B11"]).rename("NDMI_wet")
    ndvi_amp = ndvi_wet.subtract(ndvi_dry).rename("NDVI_amp")
    ndvi_p10 = p10.normalizedDifference(["B8", "B4"]).rename("NDVI_p10")
    ndmi_p10 = p10.normalizedDifference(["B8", "B11"]).rename("NDMI_p10")
    ndvi_p90 = p90.normalizedDifference(["B8", "B4"]).rename("NDVI_p90")
    ndmi_p90 = p90.normalizedDifference(["B8", "B11"]).rename("NDMI_p90")
    ndvi_p_amp = ndvi_p90.subtract(ndvi_p10).rename("NDVI_p_amp")

    return {
        "ndvi": ndvi,
        "ndmi": ndmi,
        "mndwi": mndwi,
        "ndbi": ndbi,
        "ndvi_dry": ndvi_dry,
        "ndmi_dry": ndmi_dry,
        "ndbi_dry": ndbi_dry,
        "ndvi_wet": ndvi_wet,
        "ndmi_wet": ndmi_wet,
        "ndvi_amp": ndvi_amp,
        "ndvi_p10": ndvi_p10,
        "ndmi_p10": ndmi_p10,
        "ndvi_p90": ndvi_p90,
        "ndmi_p90": ndmi_p90,
        "ndvi_p_amp": ndvi_p_amp,
    }


# Band order must match masterClassifier_D inputProperties exactly.
PHENO_BAND_ORDER = [
    "NDVI_dry",
    "NDMI_dry",
    "NDVI_amp",
    "NDMI",
    "NDBI",
    "NDVI",
    "NDVI_wet",
    "NDMI_wet",
    "NDVI_p10",
    "NDMI_p10",
    "NDVI_p90",
    "NDMI_p90",
    "NDVI_p_amp",
    "RUE",
]


def build_pheno_stack(idx: dict, rue_img):
    """Build the 14-band phenological stack used in Model D training.

    ``rue_img`` must be a single band named ``'RUE'``.
    """
    import ee

    return ee.Image.cat(
        [
            idx["ndvi_dry"],  # 1
            idx["ndmi_dry"],  # 2
            idx["ndvi_amp"],  # 3
            idx["ndmi"],  # 4
            idx["ndbi"],  # 5
            idx["ndvi"],  # 6
            idx["ndvi_wet"],  # 7
            idx["ndmi_wet"],  # 8
            idx["ndvi_p10"],  # 9
            idx["ndmi_p10"],  # 10
            idx["ndvi_p90"],  # 11
            idx["ndmi_p90"],  # 12
            idx["ndvi_p_amp"],  # 13
            rue_img,  # 14, RUE
        ]
    )
