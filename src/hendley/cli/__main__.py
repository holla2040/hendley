"""Allow `python -m hendley.cli <cmd>` (documented no-install fallback)."""

from . import main

raise SystemExit(main())
