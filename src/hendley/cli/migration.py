"""Migration commands — scr (Fusion .scr script generation)."""

from __future__ import annotations

import json
import sys


def cmd_scr(client, args) -> int:
    """Generate a Fusion ``.scr`` migration script from one or more swap files."""
    from pathlib import Path

    from ..migration.fusion_script.scr import load_swaps_json, render_script

    swaps = []
    design = args.design
    for path in args.swaps_json:
        swaps.extend(load_swaps_json(path))
        if design is None:  # pick up "design" from the first file that names one
            doc = json.loads(Path(path).read_text())
            if isinstance(doc, dict) and doc.get("design"):
                design = str(doc["design"])

    script = render_script(swaps, design=design)
    if args.output:
        Path(args.output).write_text(script)
        print(f"wrote {len(swaps)} swap(s) to {args.output}", file=sys.stderr)
        print("run it in Fusion: File > Execute Script  (Electronics workspace active),\n"
              "or in the text command line (Py): "
              f'import neu_dev; neu_dev.run_text_command("SCRIPT {args.output}")',
              file=sys.stderr)
    else:
        print(script, end="")
    return 0
