"""
Make the repository root importable so tests can import the analysis modules
directly (e.g. `from iq_snr_trace import compute_bands`) without installing
the project as a package.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
