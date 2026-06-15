# Publishing VibeIntent

This is the low-drama release checklist for a first Python package.

## What Makes This A Real Pip Package

The important files are:

- `pyproject.toml`: package metadata, build backend, Python version, console script.
- `src/vibeintent/`: importable package code.
- `src/vibeintent/__main__.py`: enables `python -m vibeintent`.
- `src/vibeintent/py.typed`: tells type checkers this package ships typed Python.
- `LICENSE`: lets other people legally use the package.
- `CHANGELOG.md`: records user-visible changes by version.
- `README.md`: becomes the PyPI project description.

The key packaging decision is the `src/` layout. It forces tests and local usage to import the installed package path, not an accidental top-level folder.

## Local Development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
vibeintent --version
python -m unittest discover -s tests
```

## Build Locally

Install build tools:

```bash
python -m pip install -U build twine
```

Build source and wheel distributions:

```bash
python -m build
python -m twine check dist/*
```

You should see:

```text
Checking dist/...: PASSED
```

## TestPyPI Dry Run

Upload to TestPyPI first:

```bash
python -m twine upload --repository testpypi dist/*
```

Then install from TestPyPI in a clean environment:

```bash
python3 -m venv /tmp/vibeintent-testpypi
. /tmp/vibeintent-testpypi/bin/activate
python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ vibeintent
vibeintent --version
```

## Real PyPI Release

Only do this after TestPyPI works:

```bash
python -m twine upload dist/*
```

## Version Bump Checklist

Before each release:

- Update `src/vibeintent/__init__.py`.
- Update `pyproject.toml`.
- Update `CHANGELOG.md`.
- Run tests.
- Build with `python -m build`.
- Check with `python -m twine check dist/*`.

