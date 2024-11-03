# seagliderOG1

This repository is intended to convert Seaglider basestation files (`pSSSDDDD*.nc`) into [OG1 format](https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html).

Code is based on code from [votoutils](https://github.com/voto-ocean-knowledge/votoutils/blob/main/votoutils/glider/convert_to_og1.py).

### Organisation

Scripts within the `seagliderOG1` package are divided by functionality:

- **readers.py** reads basestation files (`*.nc`) from a server or local directory
- **convertOG1.py** converts the basestation files to OG1 format
- **plotters.py** contains some basic plotting and viewing functions
- **vocabularies.py** contains some of the vocabulary translation (might be better as a YAML file)
- **attr_input.py** contains information for attributes of the OG1 file
- *seaglider_registr.txt* has checksums for data files

Some obsolete files:
- **tools.py**, **utilities.py** has some functions which were directly copied from votoutils, and are now outdated/inapplicable.  Kept for development purposes.
- **fetchers.py** is now mostly replaced by **readers.py**

### Status

Active development by one.  Many things may break - not yet ready for collaboration.
