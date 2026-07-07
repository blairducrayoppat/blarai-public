"""Allow ``python -m tools.perf_contrib`` to invoke the CLI."""
import sys
from tools.perf_contrib.cli import main

sys.exit(main())
