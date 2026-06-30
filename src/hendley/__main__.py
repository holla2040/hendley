"""Enable ``python -m hendley`` as an alias for the ``hendley`` CLI.

Lets the tool run without the installed entry-point script — handy on a fresh
checkout where ``pip install -e .`` hasn't put ``hendley`` on PATH (or the venv
isn't activated): ``PYTHONPATH=src python -m hendley <cmd>``.
"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
