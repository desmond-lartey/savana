# Contributing

Contributions are welcome! `savana` is designed as a foundation — new
sensors, feature stacks, classification schemes, and utilities should be
addable as independent modules without breaking the existing API.

## Reporting bugs

Please open an issue at
[github.com/desmond-lartey/savana/issues](https://github.com/desmond-lartey/savana/issues)
with:

- Your OS and Python version
- The `savana` version (`savana.__version__`)
- Steps to reproduce, including the AOI type you used

## Development setup

```bash
git clone https://github.com/desmond-lartey/savana.git
cd savana
pip install -e ".[dev,docs,vector]"
pytest tests/
```

## Pull requests

- Keep new functionality in its own module where possible (mirroring the
  existing `composites` / `indices` / `masks` / `classifiers` split)
- Add or update tests in `tests/`
- Update the docs (`docs/`) if you add public API surface — everything in
  `savana.__init__._LAZY_SYMBOL_MAP` should have a corresponding docstring
  picked up in [API Reference](api.md)
