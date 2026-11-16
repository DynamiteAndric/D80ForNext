import sys
from pathlib import Path

# the Python modules and helper scripts live in tools/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
