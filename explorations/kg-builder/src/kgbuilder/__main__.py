"""Module entry point: `python -m kgbuilder` delegates to kgbuilder.cli."""
from __future__ import annotations

import sys

from kgbuilder.cli import main

if __name__ == "__main__":
    sys.exit(main())
