# Getting Started: Installation

This guide walks you through installing and using the `seagliderOG1` Python package.  It includes:

1. Basic installation via `pip` (for most users)
2. Cloning the repo for custom use or development
3. Setup for contributors

---

## Option 1: Install via `pip` (recommended for most users)

If you just want to use the package without modifying the code:

```bash
pip install seagliderOG1
```

Then in your Python scripts or notebooks:
```python
import seagliderOG1
```
💡 You can install into a virtual environment (e.g. using venv, conda, or micromamba) to keep things clean.

---

## Option 2: Clone for custom use

If you want a local editable copy of the code, for example to adapt it to your own purposes:


#### a. Clone the repository to your computer
From a **terminal**:
```bash
git clone https://github.com/ocean-uhh/seagliderOG1
cd seagliderOG1
```

Or using **Github Desktop**:

1. Visit https://github.com/ocean-uhh/seagliderOG1
2. Click the green <> Code button
3. Choose **Open with GitHub Desktop**

💡 Rename the folder if desired.

#### b. Set up a Python environment and install

```bash
python3 -m venv venv
source venv/bin/activate # On Windows use `venv\Scripts\activate`
pip install -r requirements.txt
pip install -e . # Editable install
```

---

## Option 3: Contribute to the project 

To contribute to development:

1. Fork the repository on GitHub
2. Clone your fork locally
3. Set up a virtual environment and install dev tools:
```bash
pip install -r requirements-dev.txt
```
4. Run tests:
```bash
pytest
```

For full guidance on contributing to a project like `seagliderOG1`, see https://eleanorfrajka.github.io/template-project/gitcollab.html.
