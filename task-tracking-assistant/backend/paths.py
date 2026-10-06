"""Where things live. Run from source: next to the project. Run as the exe: DATA next to TaskFlow.exe (so replacing
the exe on update never touches tracker.db, .env or the password), CODE bundled inside the exe."""
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    DATA_DIR = Path(sys.executable).resolve().parent
    CODE_DIR = Path(getattr(sys, "_MEIPASS", DATA_DIR))
else:
    DATA_DIR = CODE_DIR = Path(__file__).resolve().parent.parent
STATIC = CODE_DIR / "static"
