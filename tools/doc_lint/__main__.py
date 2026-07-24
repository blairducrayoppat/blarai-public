"""``python -m tools.doc_lint`` entry point."""
from __future__ import annotations

import sys

from tools.doc_lint.cli import main

if __name__ == "__main__":
    sys.exit(main())
