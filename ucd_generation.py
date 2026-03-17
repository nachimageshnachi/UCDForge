"""
UCD Generation — thin orchestrator.

This module was refactored from a 1951-line monolith into a 9-step wizard.
All logic now lives in the ``generation/`` package:
  • generation/step_manager.py  — wizard navigation and state management
  • generation/shared.py        — shared utilities (SVG, colors, suggestions)
  • generation/step1_input.py … step9_cbr_export.py — one file per step

The old monolith is preserved as ``ucd_generation_old2.py`` for reference.
"""

from generation.step_manager import run_wizard


def app():
    """Entry point called by main.py."""
    run_wizard()
