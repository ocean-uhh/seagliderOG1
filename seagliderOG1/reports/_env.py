"""Jinja2 environment for seagliderOG1 report pages.

Templates load from the owned ``templates/`` first, then the vendored
``_vendored/templates/`` (so shared partials like ``_nc_tables.html`` resolve); an owned
template shadows a vendored one of the same name. The report layer's dependencies
(jinja2, numpy, matplotlib) are core, so there is no ``[report]`` extra.
"""

from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, Template

from seagliderOG1.reports import design
from seagliderOG1.reports._vendored.css import _JS_SORT_TABLES
from seagliderOG1.reports._vendored.figure_png import source_of

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_VENDORED_TEMPLATES_DIR = Path(__file__).parent / "_vendored" / "templates"

_loader = ChoiceLoader(
    [
        FileSystemLoader(str(_TEMPLATES_DIR)),
        FileSystemLoader(str(_VENDORED_TEMPLATES_DIR)),
    ]
)

_env: Environment = Environment(loader=_loader, autoescape=True)
# source_of() maps a base64 token to "module.py:func"; show_source gates its emission.
# The conversion page has no figures, so show_source is effectively unused, but the
# vendored macros reference both globals.
_env.globals["source_of"] = source_of
_env.globals["show_source"] = design.FIGURE_SOURCE
# Click-to-sort script, emitted once per page so every table sorts.
_env.globals["js_sort_tables"] = _JS_SORT_TABLES


def get_template(name: str) -> Template:
    """Return an autoescaped Jinja2 template by filename.

    Parameters
    ----------
    name : str
        The template filename (owned templates shadow vendored ones).

    Returns
    -------
    jinja2.Template
        The loaded template.

    """
    return _env.get_template(name)
