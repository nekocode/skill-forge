"""Shared test fixtures."""

import sys
from pathlib import Path

_root = Path(__file__).parent.parent

# allow tests/ to import scripts (incl. shared) and hooks modules directly
sys.path.insert(0, str(_root / "skills" / "skill-forge" / "scripts"))
sys.path.insert(0, str(_root / "hooks"))
