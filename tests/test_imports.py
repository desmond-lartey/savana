"""Import-time smoke tests.

These deliberately do NOT call ee.Initialize() / hit Earth Engine,
they only verify that the lazy-loading package structure resolves
correctly, so CI can run them without EE credentials.
"""

import savana


def test_top_level_import_is_lazy_and_fast():
    assert hasattr(savana, "__version__")


def test_lazy_symbols_resolve():
    assert callable(savana.classify_landscape)
    assert callable(savana.SavanaClassifier)
    assert callable(savana.sentinel2_annual)
    assert callable(savana.compute_indices)
    assert callable(savana.compute_thresholds)
    assert callable(savana.compute_masks)
    assert callable(savana.build_gcps)
    assert callable(savana.train_all_models)
    assert callable(savana.classify_all_epochs)
    assert callable(savana.analyse_change)


def test_lazy_submodules_resolve():
    assert savana.config.CLASS_PROPERTY == "landSystem"
    assert 1 in savana.config.DEFAULT_CLASS_INFO


def test_default_class_info_has_six_classes():
    info = savana.config.DEFAULT_CLASS_INFO
    assert len(info) == 6
    for code, entry in info.items():
        assert "name" in entry and "color" in entry


def test_dir_includes_public_api():
    d = dir(savana)
    assert "classify_landscape" in d
    assert "SavanaClassifier" in d
