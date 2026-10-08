# seagliderOG1

[![Run tests](https://github.com/ocean-uhh/seagliderOG1/actions/workflows/tests.yml/badge.svg)](https://github.com/ocean-uhh/seagliderOG1/actions/workflows/tests.yml)
[![Deploy Documentation](https://github.com/ocean-uhh/seagliderOG1/actions/workflows/docs_deploy.yml/badge.svg)](https://github.com/ocean-uhh/seagliderOG1/actions/workflows/docs_deploy.yml)

seagliderOG1 converts Seaglider basestation files (`pSSSDDDD*.nc`) into [OceanGliders OG1 format](https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html). One mission in, one OG1 file out; the platform, contributor and institution metadata come from a `mission.yaml` you keep with your data, never from defaults inside the package. Based on [votoutils](https://github.com/voto-ocean-knowledge/votoutils/blob/main/votoutils/glider/convert_to_og1.py)' `convert_to_og1`.

## Install

```bash
pip install seagliderOG1
# or from source
pip install git+https://github.com/ocean-uhh/seagliderOG1.git
```

## Quick start

```bash
seagliderOG1 init --from /data/005/20080606 -o sg005.yaml   # template from the first file
seagliderOG1 validate sg005.yaml                            # config, source, dive range
seagliderOG1 process  sg005.yaml                            # -> <output_dir>/<id>.nc
```

For a root of `SN/DATE` mission directories, point `--source` at the root and select with `--all` or `--mission GLOB`; `-n` previews without writing. `mission.yaml` holds the source, output directory, dive range, platform block, and the contributor and institution records; paths in it resolve relative to the file.

## Python

```python
from seagliderOG1 import convertOG1, readers, writers

datasets = readers.load_basestation_files(source, first, last)
ds, _ = convertOG1.convert_to_OG1(
    datasets,
    contributors=[{"name": "Jane Doe", "role": "PI", "email": "jane@example.org"}],
    institutions=[{"name": "University of Hamburg (IfM)", "role": "Operator"}],
)
writers.save_dataset(ds, out)
```

`contributors` and `institutions` are lists of records, one entry per person (or institution) per role; see the CLI reference in the documentation.

## Documentation

[Documentation and CLI reference](https://github.com/ocean-uhh/seagliderOG1); the `notebooks/demo.ipynb` notebook is a worked example.

## Acknowledgements

seagliderOG1 is developed at the University of Hamburg (ocean-uhh) in preparation for the DFG (Deutsche Forschungsgemeinschaft) research infrastructure Swarm of Ocean Gliders (Projektnummer 544335393). It converts Seaglider basestation files into OceanGliders OG1 format, driven by a mission configuration the user owns.

The work is funded by Voice of the Ocean (VOTO) under the SEA-CODE project (SeaExplorer–Seaglider Cross-platform Open Diagnostics & Evaluation), which builds platform-independent, open-source diagnostics for glider data — with glidertest and seagliderOG1 as its core packages — and supports exchanges between the University of Hamburg and VOTO, and by the DFG through the PycnMix project (Projektnummer 558671572).

seagliderOG1 welcomes contributions from the community. Development was assisted by Claude Code (Anthropic) and GitHub Copilot code review.

## License

See [LICENSE](LICENSE) for details.
