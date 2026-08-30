# ============================================================
# Script: fhv_reg.r
# Purpose: Shared regression/table utilities for this project. Defines
#          wrap_for_beamer(), sourced by any analysis script that writes a
#          bare-tabular etable() .tex table, so \input{reg/table} compiles
#          unchanged in both a beamer deck and a regular LaTeX document.
#          See CLAUDE.md and .claude/rules/r-code-conventions.md for the
#          full adjustbox/float nesting rules this implements.
# Inputs: none (function definitions only)
# Outputs: none (sourced, not run directly)
# Author: EK  Date: 2026-08-29
# ============================================================

# wrap_for_beamer(path)
#
# ONLY for bare-tabular etable() output (no style.tex("aer"), no manual
# \begin{table}). Never call on a file that already contains \begin{table}
# -- wrapping a float in adjustbox causes
# "! LaTeX Error: Not in outer par mode."
#
# Prepends a \@ifclassloaded{beamer} conditional: inside a beamer frame the
# tabular is wrapped in \begin{adjustbox}{max width=\linewidth} so it
# shrinks to fit; in a regular document it is left bare. Both documents
# must load \usepackage{adjustbox}.
#
# etable()'s `notes =` text is written by fixest as a line immediately
# following the tabular. Since that text is not part of the tabular
# environment, it renders correctly below the (possibly adjustbox-wrapped)
# table without any special handling here -- no notes-extraction step is
# needed for bare-tabular output.
wrap_for_beamer <- function(path) {
  lines <- readLines(path, warn = FALSE)

  wrapped <- c(
    "\\ifdefined\\ifclassloaded",
    "\\@ifclassloaded{beamer}{\\begin{adjustbox}{max width=\\linewidth}}{}",
    "\\fi",
    lines,
    "\\ifdefined\\ifclassloaded",
    "\\@ifclassloaded{beamer}{\\end{adjustbox}}{}",
    "\\fi"
  )

  writeLines(wrapped, path)
  invisible(path)
}
