"""Entrypoint for `python -m ticktock`."""

import sys

from .cli import main

sys.exit(main())
