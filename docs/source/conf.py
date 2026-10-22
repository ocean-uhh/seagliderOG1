"""Sphinx configuration for the seagliderOG1 documentation build."""

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
import datetime
import pathlib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from seagliderOG1 import mission as _mission

year = datetime.datetime.now(tz=datetime.UTC).date().year

# General information about the project.
project = "seagliderOG1"
author = "Eleanor Frajka-Williams, Till Moritz"
copyright = f"{year}, {author}"
try:
    release = _pkg_version("seagliderOG1")
except PackageNotFoundError:
    release = "0.0.0"
version = release

# -- Generated tables ----------------------------------------------------------
# The mission.yaml reference includes tables written here from the same row builders
# `seagliderOG1 init` and `seagliderOG1 list` use, so the docs cannot drift from the code.
_GENERATED = pathlib.Path(__file__).parent / "_generated"


def _list_table(columns: list[tuple[str, str]], rows: list[dict[str, str]]) -> str:
    """Return ``rows`` as an rst list-table with ``(key, header)`` columns."""
    lines = [".. list-table::", "   :header-rows: 1", ""]
    lines.append("   * - " + "\n     - ".join(h for _, h in columns))
    for row in rows:
        cells = [f"``{row[columns[0][0]]}``"] + [row[k] or "—" for k, _ in columns[1:]]
        lines.append("   * - " + "\n     - ".join(cells))
    return "\n".join(lines) + "\n"


def _write_generated_tables() -> None:
    """Write the platform and deployment tables the mission.yaml page includes."""
    _GENERATED.mkdir(exist_ok=True)
    platform = [
        {**row, "from_file": f"``{row['from_file']}``" if row["from_file"] else ""}
        for row in _mission.platform_rows()
    ]
    (_GENERATED / "platform_fields.inc").write_text(
        _list_table(
            [
                ("key", "Key"),
                ("requirement", "Requirement"),
                ("destination", "Written as"),
                ("from_file", "init --raw-dir reads"),
            ],
            platform,
        )
    )
    from seagliderOG1 import vocabularies

    section_slugs = set(vocabularies.CONFIG_GLOBAL_SECTIONS)
    sectioned = [r for r in _mission.global_rows() if r["set_in"] in section_slugs]
    (_GENERATED / "deployment_fields.inc").write_text(
        _list_table(
            [
                ("name", "Key"),
                ("set_in", "Section"),
                ("tier", "OG1 tier"),
                ("note", "Note"),
            ],
            sectioned,
        )
    )


_write_generated_tables()

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "sphinxarg.ext",
    "nbsphinx",
    "myst_parser",
]

# Napoleon settings for numpy-style docstrings
napoleon_google_docstring = False
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False

templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
exclude_patterns = ["_build"]

# If true, '()' will be appended to :func: etc. cross-reference text.
# add_function_parentheses = True

# If true, the current module name will be prepended to all description
# unit titles (such as .. function::).
# add_module_names = True

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = "sphinx"


# If true, keep warnings as "system message" paragraphs in the built documents.
# keep_warnings = False


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
html_theme = "sphinx_rtd_theme"

# The name for this set of Sphinx documents.  If None, it defaults to
# "<project> v<release> documentation".
# html_title = None

# A shorter title for the navigation bar.  Default is the same as html_title.
# html_short_title = None

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]

# custom CSS files
# html_context = {
#    "css_files": ["_static/css/custom.css"],
# }
html_css_files = [
    "css/custom.css",
]

# If not '', a 'Last updated on:' timestamp is inserted at every page bottom,
# using the given strftime format.
# html_last_updated_fmt = '%b %d, %Y'

source_suffix = [".rst", ".md"]

# The name of an image file (relative to this directory) to place at the top
# of the sidebar.
html_logo = "_static/logo_seaglider.png"

# If false, no index is generated.
# html_use_index = True

# If true, the index is split into individual pages for each letter.
# html_split_index = False

# The name of an image file (within the static path) to use as favicon of the
# docs.  This file should be a Windows icon file (.ico) being 16x16 or 32x32
# pixels large.
# html_favicon = None

# If true, "(C) Copyright ..." is shown in the HTML footer. Default is True.
# html_show_copyright = True

# If true, "Created using Sphinx" is shown in the HTML footer. Default is True.
# html_show_sphinx = True

# -- Options for LaTeX output ---------------------------------------------

latex_elements = {
    # The paper size ('letterpaper' or 'a4paper').
    # 'papersize': 'letterpaper',
    # The font size ('10pt', '11pt' or '12pt').
    # 'pointsize': '10pt',
    # Additional stuff for the LaTeX preamble.
    # 'preamble': '',
}

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title,
#  author, documentclass [howto, manual, or own class]).
latex_documents = [
    (
        "index",
        "seagliderOG1.tex",
        "seagliderOG1 Documentation",
        author,
        "manual",
    ),
]

# The name of an image file (relative to this directory) to place at the top of
# the title page.
# latex_logo = None

# For "manual" documents, if this is true, then toplevel headings are parts,
# not chapters.
# latex_use_parts = False

# If true, show page references after internal links.
# latex_show_pagerefs = False

# If true, show URL addresses after external links.
# latex_show_urls = False

# Documents to append as an appendix to all manuals.
# latex_appendices = []

# If false, no module index is generated.
# latex_domain_indices = True
