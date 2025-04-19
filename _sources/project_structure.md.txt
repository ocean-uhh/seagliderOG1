# What's in `seagliderOG1` project?

## 🔍 Project Structure Overview

The overall structure of the `seagliderOG1` package is as below.

```
seagliderOG1/
├── seagliderOG1                  # [core] Main Python package with scientific code
│   ├── __init__.py               # [core] Makes this a Python package
│   ├── convertOG1.py             # [core] Functions to convert data into OG1 format
│   ├── plotters.py               # [core] Functions to plot data
│   ├── readers.py                # [core] Functions to read raw data into xarray datasets
│   ├── writers.py                # [core] Functions to write data (e.g., to NetCDF)
│   ├── tools.py                  # [core] Utilities for unit conversion, calculations, etc.
│   ├── vocabularies.py           # [core] Vocabularies for OG1 format & standardisation
│   ├── logger.py                 # [core] Structured logging configuration for reproducible runs
│   ├── template_project.mplstyle # [core] Default plotting parameters
│   └── utilities.py              # [core] Helper functions (e.g., file download or parsing)
│
├── tests/                        # [test] Unit tests using pytest
│   ├── test_readers.py           # [test] Test functions in readers.py
│   ├── test_tools.py             # [test] Test functions in tools.py
│   ├── test_utilities.py         # [test] Test functions in utilities.py
│   └── ...
│
├── docs/                         # [docs]
│   ├── source/                   # [docs] Sphinx documentation source files
│   │   ├── conf.py               # [docs] Setup for documentation
│   │   ├── index.rst             # [docs] Main page with menus in *.rst
│   │   ├── setup.md              # [docs] One of the documentation pages in *.md
│   │   ├── project_structure.md  # [docs] This doc, to describe the project structure
│   │   ├── seagliderOG1.rst      # [docs] The file to create the API based on docstrings
│   │   ├── ...                   # [docs] More *.md or *.rst linked in index.rst
│   │   └── _static               # [docs] Figures
│   │       ├── css/custom.css    # [docs, style] Custom style sheet for docs
│   │       └── logo.png          # [docs] logo for top left of docs/
│   └── Makefile                  # [docs] Build the docs
│
├── notebooks/                    # [demo] Example notebooks
│   ├── demo.ipynb                # [demo] Also run in docs.yml to appear in docs
│   └── run_dataset.ipynb         # [demo] To run a full dataset through conversion
│
├── data/                         # [data]
│   └── demo_single_test.nc       # [data] Example data file 
│
├── logs/                         # [core] Log output from structured logging
│   └── *.log                     # [core] Log file describing a conversion
│
├── .github/                      # [ci] GitHub-specific workflows (e.g., Actions)
│   ├── workflows/
│   │   ├── docs.yml              # [ci] Test build documents on *pull-request*
│   │   ├── docs_deploy.yml       # [ci] Build and deploy documents on "merge"
│   │   ├── pypi.yml              # [ci] Package and release on GitHub.com "release"
│   │   └── test.yml              # [ci] Run pytest on tests/test_<name>.py on *pull-request*
│   ├── ISSUE_TEMPLATE.md         # [ci, meta] Template for issues on Github
│   └── PULL_REQUEST_TEMPLATE.md  # [ci, meta] Template for pull requests on Github
│
├── .gitignore                    # [meta] Exclude build files, logs, data, etc.
├── requirements.txt              # [meta] Pip requirements
├── requirements-dev.txt          # [meta] Pip requirements for development (docs, tests, linting)
├── .pre-commit-config.yaml       # [style] Instructions for pre-commits to run (linting)
├── pyproject.toml                # [ci, meta, style] Build system and config linters
├── CITATION.cff                  # [meta] So Github can populate the "cite" button
├── README.md                     # [meta] Project overview and getting started
└── LICENSE                       # [meta] Open source license (e.g., MIT as default)
```

The tags above give an indication of what parts of this project are used for what purposes, where:
- `# [core]` – Scientific core logic or core functions used across the project.
<!--- `# [api]` – Public-facing functions or modules users are expected to import and use.-->
- `# [docs]` – Documentation sources, configs, and assets for building project docs.
- `# [test]` – Automated tests for validating functionality.
- `# [demo]` – Notebooks and minimal working examples for demos or tutorials.
- `# [data]` – Sample or test data files.
- `# [ci]` – Continuous integration setup (GitHub Actions).
- `# [style]` – Configuration for code style, linting, and formatting.
- `# [meta]` – Project metadata (e.g., citation info, license, README).

**Note:** If you run this locally, there may also be files that you could generate but which don't necessarily appear in the project on GitHub.com (due to being ignored by your `.gitignore`).  These may include your environment (`venv/`, if you use pip and virtual environments), distribution files `dist/` for building packages to deploy on http://pypi.org, `htmlcov/` for coverage reports for tests, `seagliderOG1.egg-info` for editable installs (e.g., `pip install -e .`).

## 💡 Notes

- **Modularity**: Code is split by function (reading, writing, tools).
- **Logging**: All major functions support structured logging to `logs/`.
- **Tests**: Pytest-compatible tests are in `tests/`, with one file per module.
- **Docs**: Sphinx documentation is in `docs/`.

