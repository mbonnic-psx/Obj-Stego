"""Allow `python -m objstego` to behave exactly like the installed script."""

import sys

from .cli import main

sys.exit(main())
