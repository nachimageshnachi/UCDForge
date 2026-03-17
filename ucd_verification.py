"""
UCD Verification — thin orchestrator.

This module was refactored from a monolith into the ``verification/`` package:
  • verification/nlp_setup.py          — NLP model loading and caching
  • verification/text_tools.py         — TextVerificationTools (NLP checks)
  • verification/element_verification.py — element-level verification rules
  • verification/activity_panel.py     — TTool activity diagram builder
  • verification/xml_parser.py         — TTool XML extraction & processing
  • verification/ttool_launcher.py     — TTool executable launcher
  • verification/ui_page.py            — Streamlit UI page

The old monolith is preserved as ``ucd_validation.py`` /
``ucd_validation_operation.py`` for reference.
"""

from verification.step_manager import run_wizard


def app():
    """Entry point called by main.py."""
    run_wizard()
