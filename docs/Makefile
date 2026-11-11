# Minimal makefile for Sphinx documentation
#

# You can set these variables from the command line, and also
# from the environment for the first two.
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = source
BUILDDIR      = build

# Put it first so that "make" without argument is like "make help".
help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help Makefile report units phase

# Regenerate the hosted sg271 report pages into _static/demo/ before building, so a local
# `make html` mirrors CI. Uses the CLI (init --example -> process --report), not the demo
# notebook, so it needs no jupyter kernel; the sample is converted in a temp dir and only the
# HTML pages are kept, under their own names (they link to each other by name), with the
# conversion page also as index.html, the entry the docs link to.
report:
	@cd .. && tmp=$$(mktemp -d) && \
	  python -m seagliderOG1.cli init --example "$$tmp/sg271.yaml" --force >/dev/null && \
	  ( cd "$$tmp" && python -m seagliderOG1.cli process sg271.yaml --force >/dev/null ) && \
	  id=$$(python -c "import seagliderOG1.readers as r; print(r.SAMPLE_ID)") && \
	  rm -rf docs/source/_static/demo && mkdir -p docs/source/_static/demo && \
	  cp "$$tmp/$${id}"_*.html docs/source/_static/demo/ && \
	  cp "$$tmp/$${id}_conversion.html" docs/source/_static/demo/index.html && \
	  rm -rf "$$tmp" && \
	  echo "regenerated docs/source/_static/demo/ ($$(ls docs/source/_static/demo | wc -l | tr -d ' ') pages)"

units:
	@cd .. && python docs/generate_units_map.py

# The figures on the Phase page, from the bundled samples.
phase:
	@cd .. && python docs/generate_phase_figures.py

# html regenerates the generated pages first; the demo notebook (demo-output.ipynb) is produced by
# nbconvert (CI, or by hand) — it needs a jupyter kernel and is not required to refresh them.
html: report units phase
	@$(SPHINXBUILD) -M html "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
