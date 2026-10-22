# seagliderOG1

[![PyPI](https://img.shields.io/pypi/v/seagliderOG1.svg)](https://pypi.org/project/seagliderOG1/)
[![Python versions](https://img.shields.io/pypi/pyversions/seagliderOG1.svg)](https://pypi.org/project/seagliderOG1/)
[![License: MIT](https://img.shields.io/github/license/ocean-uhh/seagliderOG1.svg)](https://github.com/ocean-uhh/seagliderOG1/blob/main/LICENSE)
[![Tests](https://github.com/ocean-uhh/seagliderOG1/actions/workflows/tests.yml/badge.svg)](https://github.com/ocean-uhh/seagliderOG1/actions/workflows/tests.yml)
[![Documentation](https://img.shields.io/badge/docs-ocean--uhh.github.io-blue.svg)](https://ocean-uhh.github.io/seagliderOG1/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23574871.svg)](https://doi.org/10.5281/zenodo.23574871)

seagliderOG1 converts Seaglider basestation files (`pSSSDDDD*.nc`) into [OceanGliders OG1 format](https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html). One mission in, one OG1 file out; the platform, contributor and institution metadata come from a `mission.yaml` you keep with your data, never from defaults inside the package. Based on [votoutils](https://github.com/voto-ocean-knowledge/votoutils/blob/main/votoutils/glider/convert_to_og1.py)' `convert_to_og1`.

## Install

```bash
pip install seagliderOG1
# or from source
pip install git+https://github.com/ocean-uhh/seagliderOG1.git
```

## Quick start

```bash
seagliderOG1 draft --raw-dir /data/005/20080606             # see the data first: a draft page, no config
seagliderOG1 init sg005.yaml --raw-dir /data/005/20080606   # template from the first file
seagliderOG1 validate sg005.yaml                            # config, raw_dir, dive range
seagliderOG1 process  sg005.yaml                            # -> <output_dir>/<id>.nc
seagliderOG1 report   <output_dir>/<id>.nc                  # the conversion page
```

For a root of `SN/DATE` mission directories, point `--raw-dir` at the root and select with `--all` or `--mission GLOB`; `-n` previews without writing. `mission.yaml` holds the raw-data directory (`raw_dir`), output directory, dive range, platform block, and the contributor and institution records; paths in it resolve relative to the file.

## Python

```python
from seagliderOG1 import convert, readers, writers

datasets = readers.read_mission(source, first, last)
ds = convert.to_og1(
    datasets,
    contributors=[{"name": "Jane Doe", "role": "PI", "email": "jane@example.org"}],
    institutions=[{"name": "University of Hamburg", "role": "Operator"}],
)
writers.write(ds, out)
```

`contributors` and `institutions` are lists of records, one entry per person (or institution) per role; see the CLI reference in the documentation.

## Documentation

[Documentation and CLI reference](https://ocean-uhh.github.io/seagliderOG1); the `notebooks/demo.ipynb` notebook is a worked example.

## Acknowledgements

seagliderOG1 converts Seaglider basestation files into OceanGliders OG1 format, driven by a mission configuration the user owns. It was started at the University of Hamburg (ocean-uhh) in preparation for the DFG (Deutsche Forschungsgemeinschaft) research infrastructure Swarm of Ocean Gliders (Projektnummer 544335393).

Initial development was supported by Voice of the Ocean (VOTO) under the SEA-CODE project (SeaExplorer–Seaglider Cross-platform Open Diagnostics & Evaluation), which builds platform-independent, open-source diagnostics for glider data — with glidertest and seagliderOG1 as its core packages — and supports exchanges between the University of Hamburg and VOTO, and, at the University of Hamburg, by the DFG through the PycnMix project (Projektnummer 558671572).

seagliderOG1 is an open community project; [CONTRIBUTING.md](CONTRIBUTING.md) covers licensing, credit and scope. Development was assisted by Claude Code (Anthropic) and GitHub Copilot code review.

## License

See [LICENSE](LICENSE) for details.
