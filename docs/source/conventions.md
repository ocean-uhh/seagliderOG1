# Coding Conventions

This document outlines the coding standards and conventions for the seagliderOG1 project.

## Code Style

### Python Code Formatting

We use [Black](https://black.readthedocs.io/) for consistent code formatting:

```bash
black .
```

**Key formatting rules:**
- Line length: 88 characters (Black default)
- Use double quotes for strings
- Consistent indentation (4 spaces)
- Trailing commas in multi-line structures

### Linting

We use [Ruff](https://docs.astral.sh/ruff/) for fast Python linting:

```bash
ruff check --fix  # Auto-fix issues where possible
ruff check        # Check without fixing
```

**Enabled rule categories:**
- `E`, `W` - pycodestyle errors and warnings
- `F` - pyflakes errors  
- `D` - pydocstyle (documentation)
- `ANN` - type annotations
- `B` - flake8-bugbear
- `C90` - mccabe complexity
- `TRY` - tryceratops
- `ARG` - flake8-arguments
- `SLF` - flake8-self

### Pre-commit Hooks

Run before every commit:

```bash
pre-commit run --all-files
```

This automatically runs:
- Black formatting
- Ruff linting with auto-fix
- Codespell for typos
- Basic file checks (trailing whitespace, end-of-file, YAML validation)
- pytest tests

## Code Organization

### File Structure

Follow the established package structure:

```
seagliderOG1/
├── readers.py      # Data input/reading functions
├── writers.py      # Data output/writing functions  
├── convertOG1.py   # Main conversion logic
├── tools.py        # User-facing utility functions
├── utilities.py    # Internal helper functions
├── vocabularies.py # OG1 vocabulary mappings
└── plotters.py     # Visualization functions
```

### Import Organization

Order imports following PEP 8:

```python
# Standard library
import logging
import os
from datetime import datetime

# Third-party packages
import numpy as np
import pandas as pd
import xarray as xr

# Local imports
from seagliderOG1 import utilities, vocabularies
```

## Documentation

### Docstrings

Use numpy-style docstrings for all public functions:

```python
def convert_to_OG1(list_of_datasets, contrib_to_append=None):
    """
    Processes datasets and converts them to OG1 format.

    Parameters
    ----------
    list_of_datasets : list[xr.Dataset] | xr.Dataset
        A list of xarray datasets or a single dataset in basestation format.
    contrib_to_append : dict[str, str] | None, optional
        Dictionary containing additional contributor information. Default is None.

    Returns
    -------
    tuple[xr.Dataset, list[str]]
        A tuple containing:
        - ds_og1 : xr.Dataset
            The processed dataset in OG1 format.
        - varlist : list[str]
            A list of variable names from input datasets.

    Raises
    ------
    ValueError
        If input datasets are invalid.

    Examples
    --------
    >>> datasets = readers.load_basestation_files("path/to/files/")
    >>> og1_data, variables = convert_to_OG1(datasets)
    """
```

### Comments

- Use comments sparingly for complex logic
- Prefer self-documenting code with clear variable names
- Add TODO comments for future improvements

## Variable Naming

### Conventions

- **Functions and variables**: `snake_case`
- **Constants**: `UPPER_CASE`
- **Classes**: `PascalCase` (when needed)
- **Private functions**: `_leading_underscore`

### Dataset Variables

Follow OG1 naming conventions:
- Time coordinates: `TIME`, `TIME_GPS`
- Spatial coordinates: `LATITUDE`, `LONGITUDE`, `DEPTH`
- Measurements: Descriptive names in UPPER_CASE
- QC flags: Append `_QC` to variable name

### Descriptive Names

Prefer descriptive names over abbreviations:

```python
# Good
temperature_data = ds["TEMP"]
pressure_sensor = ds["PRES"] 
dive_number = ds.attrs["dive_number"]

# Avoid
temp = ds["TEMP"]
p = ds["PRES"]
dn = ds.attrs["dive_number"]
```

## Testing

### Test Structure

- Place tests in `tests/` directory
- Mirror package structure: `test_module.py` for each `module.py`
- Use pytest for all testing

### Test Naming

```python
def test_convert_to_og1_single_dataset():
    """Test conversion with a single input dataset."""
    pass

def test_convert_to_og1_multiple_datasets():
    """Test conversion with multiple input datasets."""
    pass
```

### Coverage

- Aim for good test coverage of public functions
- Test both success and failure cases
- Include edge cases and boundary conditions

## Data Handling

### xarray Best Practices

- Use descriptive coordinate and dimension names
- Set appropriate attributes for variables
- Handle missing data consistently (use NaN)
- Use `.compute()` for dask arrays when needed

### File I/O

- Use context managers for file operations
- Handle file paths consistently (use pathlib when appropriate)
- Provide informative error messages for I/O failures

## Error Handling

### Logging

Use the standard logging module:

```python
import logging

_log = logging.getLogger(__name__)

def process_data(data):
    _log.info("Starting data processing")
    try:
        result = expensive_operation(data)
        _log.debug(f"Processed {len(result)} items")
        return result
    except Exception as e:
        _log.error(f"Failed to process data: {e}")
        raise
```

### Exception Handling

- Use specific exception types when possible
- Provide helpful error messages
- Log errors appropriately
- Don't suppress exceptions without good reason

## Performance

### Efficiency Guidelines

- Use vectorized operations with NumPy/pandas
- Avoid unnecessary data copying
- Use appropriate data types (e.g., float32 vs float64)
- Consider memory usage for large datasets

### Memory Management

- Use generators for large data processing
- Clear large variables when no longer needed
- Be mindful of xarray lazy loading

## Version Control

### Commit Messages

Use clear, descriptive commit messages:

```
[FEAT] Add GPS coordinate interpolation
[FIX] Handle missing pressure data in dive profiles  
[DOC] Update installation instructions
[TEST] Add tests for vocabulary mapping
```

### Branch Naming

- Feature branches: `feature/description`
- Bug fixes: `fix/description` 
- Documentation: `docs/description`

## Configuration

### YAML Files

- Use consistent indentation (2 spaces)
- Include comments for complex configurations
- Validate YAML syntax
- Follow the existing structure in `seagliderOG1/config/` directory

## Dependencies

### Adding New Dependencies

- Add to appropriate requirements file:
  - `requirements.txt` - Runtime dependencies
  - `requirements-dev.txt` - Development tools
- Use version constraints appropriately
- Document why new dependencies are needed
- Prefer established, well-maintained packages