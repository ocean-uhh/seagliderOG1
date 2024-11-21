# seagliderOG1

This repository is intended to convert Seaglider basestation files (`pSSSDDDD*.nc`) into [OG1 format](https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html).

Code is based on code from [votoutils](https://github.com/voto-ocean-knowledge/votoutils/blob/main/votoutils/glider/convert_to_og1.py).

### Organisation

Scripts within the `seagliderOG1` package are divided by functionality:

- **readers.py** reads basestation files (`*.nc`) from a server or local directory
- **writers.py** writes OG1 `*.nc` files, default directory `data/`
- **plotters.py** contains some basic plotting and viewing functions
- **convertOG1.py** converts the basestation files to OG1 format
- **vocabularies.py** contains some of the vocabulary translation (might be better as a YAML file)
- *seaglider_registr.txt* has checksums for data files
- **tools.py** functions the user may want to use
- **utilities.py** functions the user probably will never need to call (only used in other functions)

### Status

Active development by one.  Many things may break - not yet ready for collaboration.
