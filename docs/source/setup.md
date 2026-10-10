# Installation

This guide provides installation instructions for the `seagliderOG1` Python package for different use cases.

## Basic Installation (PyPI)

For most users who want to use the package:

```bash
pip install seagliderOG1
```

Then import in your Python code:
```python
import seagliderOG1
```

## Local Development Installation

```bash
# Clone the repository
git clone https://github.com/ocean-uhh/seagliderOG1.git
cd seagliderOG1

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install the package with the dev extras (dependencies are declared in pyproject.toml)
pip install -e ".[dev]"
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/ocean-uhh/seagliderOG1.git
cd seagliderOG1
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

## Contributing Installation

For contributors and developers:

### Setup

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/seagliderOG1.git
   cd seagliderOG1
   ```

3. **Set up a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. **Install the package with the dev extras**:
   ```bash
   pip install -e ".[dev]"
   ```

### Development Workflow

**Run tests:**
```bash
pytest                    # Run all tests
pytest -v                 # Verbose output
pytest tests/test_*.py    # Run specific test file
```

**Code quality checks:**
```bash
black .                   # Format code
ruff check --fix          # Lint and auto-fix
pre-commit run --all-files # Run all pre-commit hooks
```

**Before committing:**
```bash
pytest                    # Ensure tests pass
ruff check                # Check for linting issues
```

### Coding Standards

Please follow the project's coding conventions documented in [conventions.md](conventions.md), which covers:
- Code formatting (Black)
- Linting (Ruff) 
- Docstring style (numpy format)
- Import organization (PEP 8)
- Testing practices

### Contributing Guidelines

For detailed contribution guidelines, see our [contributing documentation](https://eleanorfrajka.github.io/template-project/gitcollab.html).

## Verification

Verify your installation works:

```python
from seagliderOG1 import readers, convertOG1, writers

# Load sample data
dataset = readers.load_sample_dataset()
print("✅ Installation successful!")
```