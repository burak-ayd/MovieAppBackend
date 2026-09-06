"""
Root level launcher for the interactive plugin test runner.
Kullanım:
    python test_interactive.py
"""

import sys
import asyncio
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tests.interactive_test import main

if __name__ == "__main__":
    asyncio.run(main())
