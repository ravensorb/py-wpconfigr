"""Support ``python -m l3io.wp.config``."""

import sys

from l3io.wp.config.cli.main import run

if __name__ == "__main__":
    sys.exit(run())
