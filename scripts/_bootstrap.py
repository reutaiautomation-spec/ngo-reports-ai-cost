"""Makes `import src...` work when running `python scripts/<name>.py` from anywhere."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
