# Contributing to seagliderOG1

## Development install

```bash
git clone https://github.com/ocean-uhh/seagliderOG1.git
cd seagliderOG1
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -e ".[dev]"         # dependencies are declared in pyproject.toml
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

Verify:

```bash
seagliderOG1 --help
python -c "import seagliderOG1; print(seagliderOG1.__version__)"
```

## Tests

```bash
pytest            # all tests
pytest -v         # verbose
pytest tests/test_cli.py
```

Tests mirror the package: `test_<module>.py` for each `<module>.py`. Cover success and failure
paths.

## Lint and format

[Ruff](https://docs.astral.sh/ruff/) does both:

```bash
ruff format .       # format
ruff check . --fix  # lint and auto-fix
ruff check .        # lint without fixing
```

Before a commit: `ruff check . && ruff format --check . && pytest`.

The enforced rule set is the `[tool.ruff]` `select`/`extend-select` in `pyproject.toml` (that
file is the source of truth; numpy docstring convention). Note: the existing code is **not yet
clean** under the instituted rules — the bulk fix is deferred, so `ruff check .` currently
reports pre-existing findings. Keep newly written code clean per file; a new `# noqa` names the
rule and a reason.

## Docstrings

Numpy-style docstrings on every public module, class and function, with full type information,
ending with a period. Example:

```python
def convert_to_OG1(datasets, contributors=None, institutions=None):
    """Convert basestation datasets to an OG1 dataset.

    Parameters
    ----------
    datasets : list of xarray.Dataset or xarray.Dataset
        Basestation datasets for one mission.

    Returns
    -------
    tuple of (xarray.Dataset, list of str)
        The OG1 dataset and the list of input variable names.
    """
```

## Modules and defaults

The module map and where the built-in defaults live (`config/*.yaml` and the `vocabularies.py`
tables) are in the documentation: [Package layout and
defaults](https://ocean-uhh.github.io/seagliderOG1/package_layout.html).

## Branches, commits, pull requests

Work on a branch, never on `main`; changes land via pull request.

- Branch prefixes: `feat/`, `fix/`, `docs/`, `cleanup/`, `cli/`.
- Commit messages: conventional prefixes, imperative subject — `feat:`, `fix:`, `refactor:`,
  `docs:`, `test:`, `ci:`, `chore:`.
- PR titles: a bracket tag — `[FEAT]`, `[FIX]`, `[REFACTOR]`, `[DOC]`, `[TEST]`, `[CI]`,
  `[CLEANUP]`.

## Remotes

`origin` is `ocean-uhh/seagliderOG1` (the canonical repo; PRs and pushes go here). A contributor
fork is a second remote. Name the remote in git commands rather than assuming `origin`.
