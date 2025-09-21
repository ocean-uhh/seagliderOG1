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

### Using conda/micromamba

If you prefer conda environments:

```bash
# Clone the repository
git clone https://github.com/ocean-uhh/seagliderOG1.git
cd seagliderOG1

# Create and activate environment
conda env create -f environment.yml
conda activate TEST

# Install package in editable mode
pip install -e .
```

Using micromamba (faster alternative):
```bash
micromamba env create -f environment.yml
micromamba activate TEST
pip install -e .
```

### Using pip and virtual environments

```bash
# Clone the repository
git clone https://github.com/ocean-uhh/seagliderOG1.git
cd seagliderOG1

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies and package
pip install -r requirements.txt
pip install -e .
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

3. **Set up environment** (choose one):

   **Option A: Using conda/micromamba**
   ```bash
   conda env create -f environment.yml
   conda activate TEST
   ```

   **Option B: Using pip**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. **Install development dependencies**:
   ```bash
   pip install -r requirements-dev.txt
   pip install -e .
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