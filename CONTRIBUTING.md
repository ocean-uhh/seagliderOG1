# Contributing to seagliderOG1

seagliderOG1 is a small scientific package maintained by a research group; pull requests are
reviewed by a person. The two sections on licensing and credit come first so that attribution is
settled before the work, not after it.

- Repository: <https://github.com/ocean-uhh/seagliderOG1>
- Licence: MIT (see `LICENSE`)
- Bugs and feature requests: GitHub Issues

## Licensing of contributions

seagliderOG1 is MIT licensed, and contributions are accepted under the same licence ("inbound =
outbound"). By opening a pull request you confirm that:

1. you wrote the contribution, or you have the right to submit it; and
2. you agree to license it to the project under the MIT licence.

This does not transfer your copyright, which remains yours.

If your contribution contains code from somewhere else — another repository, a paper's
supplementary material, a Stack Overflow answer, a colleague's script, generated output you did
not review — say so in the pull request and name the source and its licence. Code from an
unlicensed source cannot be merged until its author agrees, so flagging it early avoids wasted
work.

## Credit and authorship

Three separate things.

**Copyright** stays with whoever wrote the code. You are not asked to assign it.

**Contributor credit** is automatic: everyone whose pull request is merged appears in the git
history. If your name or email in the git log is wrong, open an issue; the fix is a `.mailmap`
entry.

**Citation authorship** is the list in `CITATION.cff`, which propagates into the Zenodo DOI for
every release and so into other people's bibliographies. It reflects substantial contribution to
the software — its design, a significant body of its implementation, its test suite, or its
documentation — and is decided by the maintainers at release time. Funding or supervision alone
does not qualify. There is no line count that guarantees it and none that excludes it; if you
believe your contribution crosses that line and it has not been reflected, say so in an issue.

Where a contribution is adapted from someone else's work rather than written from scratch, the
credit goes in the docstring of the code itself, so the attribution travels with the code.

## Scope

seagliderOG1 converts Seaglider basestation files (`pSSSDDDD*.nc`) into OG1 netCDF and writes a
conversion page describing what it did.

**Fixed** — changing these changes every user's output files, so open an issue before a pull
request:

- The output schema: OG1 variable names and attributes, dtypes, `_FillValue` sentinels and time
  units on disk.
- Platform, contributor and institution metadata come from the user's `mission.yaml`, never from
  defaults inside the package; a value that cannot be determined is `UNK` or an error.
- Every basestation variable is retained (renamed to OG1 or passed through under its own name),
  and the conversion records what it did in the file and its sidecar.

**Open** — added with the existing behaviour unchanged:

- Readers for other basestation versions and file layouts.
- Vocabulary mappings in `seagliderOG1/config/*.yaml` (`OG1_variable_names.yaml`,
  `OG1_variable_attributes.yaml`, `OG1_sensor_names.yaml`, `OG1_sensor_attributes.yaml`): a
  basestation variable or sensor that has an OG1 name but no mapping yet.
- Sections of the conversion page.

**Out of scope, on purpose** — quality control and OG1 compliance checks of the output belong to
[glidertest](https://github.com/OceanGlidersCommunity/glidertest), which reads any OG1 file, not
only those this package writes.

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
python -c "from importlib.metadata import version; print(version('seagliderOG1'))"
```

## Tests

```bash
pytest            # all tests
pytest -v         # verbose
pytest tests/test_cli.py
```

Tests mirror the package: `test_<module>.py` for each `<module>.py`. Cover success and failure
paths. Tests convert the real basestation files in `data/demo_sg005`; synthetic data is for pure
logic only. CI enforces a coverage floor (`--cov-fail-under` in `.github/workflows/tests.yml`).

## Lint and format

[Ruff](https://docs.astral.sh/ruff/) does both:

```bash
ruff format .       # format
ruff check . --fix  # lint and auto-fix
ruff check .        # lint without fixing
```

Before a commit: `ruff check . && ruff format --check . && pytest`.

The enforced rule set is the `[tool.ruff]` `select`/`extend-select` in `pyproject.toml` (that
file is the source of truth; numpy docstring convention). CI runs `ruff check .` and
`ruff format --check .` with the ruff version pinned in the `dev` extra. A `# noqa` names the rule
and a reason.

## Docstrings

Numpy-style docstrings on every public module, class and function, with full type information,
ending with a period; the `pyproject.toml` ruff config enforces this (`convention = "numpy"`,
`D417`). Any public function in `seagliderOG1/` is a worked example — match the one nearest what
you are writing.

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
