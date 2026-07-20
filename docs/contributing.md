# Contributing

Contributions are welcome! `savana` is designed as an umbrella for
independently-usable geospatial modules — new sensors, feature stacks,
classification schemes, validation workflows, and utilities should be
addable as their own module without breaking any existing module's API.
`savana.rainfall` (precipitation product assessment) is the second such
module, added alongside the original land-system classification pipeline
following exactly this pattern — a useful reference if you're adding a
third.

## Reporting bugs

Please open an issue at
[github.com/desmond-lartey/savana/issues](https://github.com/desmond-lartey/savana/issues)
with:

- Your OS and Python version
- The `savana` version (`savana.__version__`)
- Which module (classification or rainfall)
- Steps to reproduce — for classification, the AOI type you used; for
  rainfall, the station input and product(s) involved

## Development setup

```bash
git clone https://github.com/desmond-lartey/savana.git
cd savana
pip install -e ".[dev,docs,vector,rainfall]"
pytest tests/
```

## Pull requests

- Keep new functionality in its own module where possible — mirroring the
  existing `composites` / `indices` / `masks` / `classifiers` split for
  classification-side work, or the `stations` / `zones` / `ingestion` /
  `extraction` / `validation` split for rainfall-side work
- If you're adding an entirely new module (not extending classification or
  rainfall), give it its own subpackage under `savana/` (see
  `savana/rainfall/` for the shape: its own `__init__.py` with the same
  PEP 562 lazy-loading pattern, its own `config.py` of overridable defaults,
  its own optional-dependency extra in `pyproject.toml`)
- Add or update tests in `tests/`
- Update the docs (`docs/`) if you add public API surface — everything in
  `savana.__init__._LAZY_SYMBOL_MAP` (classification) or
  `savana.rainfall.__init__._LAZY_SYMBOL_MAP` (rainfall) should have a
  corresponding docstring picked up in the relevant
  [API Reference](api.md) / [Rainfall API Reference](api_rainfall.md) page
