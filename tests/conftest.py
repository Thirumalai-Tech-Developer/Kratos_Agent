import sys
from pathlib import Path

# Add src to sys.path so tests can import kratos_agent without editable install
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
