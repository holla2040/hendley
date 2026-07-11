"""Shared CLI helpers."""

from __future__ import annotations

import json


def print_json(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))
