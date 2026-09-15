"""pytest conftest — ensure repo root is on sys.path for `concord.*` imports."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
