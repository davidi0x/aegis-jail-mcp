#!/usr/bin/env python3
"""Run Aegis straight from a checkout or plugin directory - no installation needed."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aegis_jail.cli import main  # noqa: E402

sys.exit(main())
