# What's in `seagliderOG1` project?

## 🔍 Project Structure Overview

The overall structure of the `seagliderOG1` package is as below.

```
seagliderOG1/
├── seagliderOG1                  # [core] Main Python package with scientific code
│   ├── __init__.py               # [core] Makes this a Python package
│   ├── _version.py               # [core] Automatically generated version from git tags
│   ├── config/                   # [core] Configuration files for OG1 format conversion
│   │   ├── OG1_global_attrs.yaml # [core] Global attributes for OG1 format
│   │   ├── OG1_var_names.yaml    # [core] Variable name mappings
│   │   ├── OG1_vocab_attrs.yaml  # [core] Vocabulary attribute mappings
│   │   ├── OG1_sensor_attrs.yaml # [core] Sensor attribute definitions
│   │   ├── OG1_author.yaml       # [core] Author information template
│   │   └── mission_yaml.yaml     # [core] Mission configuration template
│   ├── convertOG1.py             # [core] Functions to convert data into OG1 format
│   ├── plotters.py               # [core] Functions to plot data
│   ├── readers.py                # [core] Functions to read raw data into xarray datasets
│   ├── writers.py                # [core] Functions to write data (e.g., to NetCDF)
│   ├── tools.py                  # [core] Utilities for unit conversion, calculations, etc.
│   ├── vocabularies.py           # [core] Vocabularies for OG1 format & standardisation
│   ├── old-tools.py              # [core] Legacy functions (deprecated)
│   └── utilities.py              # [core] Helper functions (e.g., file download or parsing)
│
├── tests/                        # [test] Unit tests using pytest
│   ├── test_convertOG1.py        # [test] Test functions in convertOG1.py
│   ├── test_plotters.py          # [test] Test functions in plotters.py
│   ├── test_readers.py           # [test] Test functions in readers.py
│   ├── test_tools.py             # [test] Test functions in tools.py
│   ├── test_utilities.py         # [test] Test functions in utilities.py
│   └── test_vocabularies.py      # [test] Test functions in vocabularies.py
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
├── data/                         # [data] Sample data files for testing and examples
│   ├── demo_single_test.nc       # [data] Example data file for basic testing
│   ├── sg*.nc                    # [data] Seaglider basestation files for testing
│   └── *.log                     # [data] Log files corresponding to data files 
│
├── .github/                      # [ci] GitHub-specific workflows (e.g., Actions)
│   ├── workflows/
│   │   ├── docs.yml              # [ci] Test build documents on *pull-request*
│   │   ├── docs_deploy.yml       # [ci] Build and deploy documents on "merge"
│   │   ├── pypi.yml              # [ci] Package and release on GitHub.com "release"
│   │   └── tests.yml             # [ci] Run pytest on tests/test_<name>.py on *pull-request*
│   ├── dependabot.yml            # [ci] Monthly GitHub Actions version bumps
│   ├── ISSUE_TEMPLATE.md         # [ci, meta] Template for issues on Github
│   └── PULL_REQUEST_TEMPLATE.md  # [ci, meta] Template for pull requests on Github
│
├── .gitignore                    # [meta] Exclude build files, logs, data, etc.
├── .pre-commit-config.yaml       # [style] Instructions for pre-commits to run (linting)
├── pyproject.toml                # [ci, meta, style] Build system, dependencies, and config
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
- **Configuration**: OG1 format specifications are defined in YAML files in `seagliderOG1/config/`.
- **Tests**: Pytest-compatible tests are in `tests/`, with one file per module.
- **Docs**: Sphinx documentation is in `docs/`.

