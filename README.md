# seagliderOG1

[![Run tests](https://github.com/ocean-uhh/seagliderOG1/actions/workflows/tests.yml/badge.svg)](https://github.com/ocean-uhh/seagliderOG1/actions/workflows/tests.yml)
[![Deploy Documentation](https://github.com/ocean-uhh/seagliderOG1/actions/workflows/docs_deploy.yml/badge.svg)](https://github.com/ocean-uhh/seagliderOG1/actions/workflows/docs_deploy.yml)

This repository converts Seaglider basestation files (`pSSSDDDD*.nc`) into [OG1 format](https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html) for standardized oceanographic glider data.

Code is based on [votoutils](https://github.com/voto-ocean-knowledge/votoutils/blob/main/votoutils/glider/convert_to_og1.py).

## Installation

### Recommended: Using pip

For most users, pip installation is the simplest approach:

```bash
# Install from PyPI (when available)
pip install seagliderOG1

# Or install from source
pip install git+https://github.com/ocean-uhh/seagliderOG1.git
```

### Development setup

For contributors and developers:

```bash
# Clone the repository
git clone https://github.com/ocean-uhh/seagliderOG1.git
cd seagliderOG1

# Install dependencies and package in development mode
pip install -r requirements-dev.txt
pip install -e .
```

### Alternative: Using conda/micromamba

If you prefer conda environments:

```bash
# Using conda
conda env create -f environment.yml
conda activate TEST

# Using micromamba (faster)
micromamba env create -f environment.yml
micromamba activate TEST
```

## Package Structure

Scripts within the `seagliderOG1` package are organized by functionality:

- **readers.py** - Reads basestation files (`*.nc`) from server or local directory
- **writers.py** - Writes OG1 `*.nc` files to output directory (default: `data/`)
- **plotters.py** - Basic plotting and data visualization functions
- **convertOG1.py** - Main conversion logic from basestation to OG1 format
- **vocabularies.py** - Vocabulary translation mappings for OG1 compliance
- **tools.py** - User-facing utility functions
- **utilities.py** - Internal helper functions for data processing

## Configuration

The `seagliderOG1/config/` directory contains YAML files that define OG1 format specifications:

- `OG1_global_attrs.yaml` - Global attributes for OG1 format
- `OG1_var_names.yaml` - Variable name mappings
- `OG1_sensor_attrs.yaml` - Sensor attribute definitions
- `OG1_vocab_attrs.yaml` - Vocabulary attribute mappings
- `OG1_author.yaml` - Author information template
- `mission_yaml.yaml` - Mission configuration template

## Usage

### Basic conversion

```python
from seagliderOG1 import convertOG1, readers

# Load basestation files
datasets = readers.load_basestation_files("path/to/basestation/files/")

# Convert to OG1 format
og1_dataset, variable_list = convertOG1.convert_to_OG1(datasets)

# Save result
from seagliderOG1 import writers
writers.save_dataset(og1_dataset, "output_file.nc")
```

### Examples

See the `notebooks/` directory for detailed examples:
- `demo.ipynb` - Basic usage demonstration
- `dev_notebooks/` - Development and troubleshooting notebooks

## Development

### Running tests

```bash
pytest                    # Run all tests
pytest -v                 # Verbose output
pytest tests/test_*.py    # Run specific test file
```

### Code quality

```bash
black .                   # Format code
ruff check --fix          # Lint and auto-fix
pre-commit run --all-files # Run all pre-commit hooks
```

### Building documentation

```bash
cd docs
make clean html
```

## Dependencies

The project uses different dependency files for different use cases:

- **requirements.txt** - Core runtime dependencies (recommended for most users)
- **requirements-dev.txt** - Additional development tools (testing, documentation, code quality)
- **environment.yml** - Complete conda/micromamba environment (alternative for conda users)

### Core dependencies

- **xarray** & **netCDF4** - NetCDF file handling and data manipulation
- **numpy**, **pandas** - Numerical operations and data structures
- **gsw** - Seawater property calculations (TEOS-10)
- **matplotlib** - Plotting and visualization
- **pooch** - Data downloading and caching

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and ensure they pass
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Status

This project is under active development. Collaborations and contributions are welcome!

## License

See [LICENSE](LICENSE) for details.
