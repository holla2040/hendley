"""ClaudeCLIInterpreter — judgment via headless Claude Code (``claude -p``).

Rides the user's existing Claude subscription: no API key, no separate
billing, works on any machine where ``claude`` is installed and logged in.
Latency is seconds per call, which the interpretation cache makes
irrelevant (each unique string is judged once, ever).

Failure of any kind — binary missing, timeout, non-JSON output, refusal —
returns ``None``: the caller falls back to the one-time confirm card. The
LLM can lower zero-touch coverage, never break the flow.
"""

from __future__ import annotations

import json
import os
import re
import subprocess

from ..domain.model import SpecKey
from .interpreter import Interpretation

DEFAULT_BIN = "claude"
TIMEOUT_S = 120

PROMPT = """\
You are the component-interpretation step of an electronics BOM tool.
A schematic part carries ad-hoc, designer-written text. Map it onto the
tool's canonical vocabulary.

Part context (verbatim from the design):
{context}

Rules:
- kind: lowercase category noun (resistor, capacitor, inductor, diode, led,
  fuse, switch, connector, ic, transistor, crystal, ...). Use the
  designator prefix and value/footprint together.
- value: canonical short form, lowercase suffixes: resistance like "22k",
  "4.7k", "220", "1M"; capacitance like "100n", "47u"; inductance like
  "22u". Extra ratings (voltage, tolerance, dielectric) belong in
  qualifier, NOT in value.
- package: normalize the library footprint name to the industry package it
  denotes, in catalog spelling:
  - a standard chip size (0201/0402/0603/0805/1206/1210/2010/2512) → that
    size ("R-0402" → "0402").
  - an embedded standard package name → the catalog form as distributors
    list it (e.g. "D-SOD323" → "SOD-323").
  - ONLY when no standard package is recognizable, keep the library
    footprint name VERBATIM (e.g. "C-E-5" — it keys the database).
- qualifier: the extra requirements as a short string (e.g. "50V",
  "1%", "X7R 25V"), or "" if none.
- envelope: your best reading of the footprint's physical reality:
  mount "smd" or "tht"; maxDiaMm / maxLenMm / leadSpacingMm when the
  footprint name or geometry implies them; omit fields you cannot infer.
  (Example: an Eagle footprint named C-E-5 is typically a radial
  electrolytic with 5 mm lead spacing, so bodies up to ~10-13 mm dia fit.)
- confidence: 0..1 — how sure you are of the WHOLE reading. Below 0.8 the
  tool will ask the engineer instead of trusting you; be honest.
- rationale: one short sentence.

Answer with ONLY this JSON object, no prose, no code fences:
{{"kind": "...", "value": "...", "package": "...", "qualifier": "...",
  "envelope": {{"mount": "smd|tht", "maxDiaMm": 0, "maxLenMm": 0,
                "leadSpacingMm": 0}},
  "confidence": 0.0, "rationale": "..."}}
"""


class ClaudeCLIInterpreter:
    """Interpretation through ``claude -p`` with strict-JSON output."""

    name = "claude-cli"

    def __init__(self, binary: str | None = None, timeout: int = TIMEOUT_S):
        self.binary = binary or os.environ.get("HENDLEY_CLAUDE_BIN", DEFAULT_BIN)
        self.timeout = timeout

    def interpret_part(self, ctx: dict) -> Interpretation | None:
        prompt = PROMPT.format(context=json.dumps(ctx, indent=2, ensure_ascii=False))
        try:
            proc = subprocess.run(
                [self.binary, "-p", prompt, "--output-format", "json"],
                capture_output=True, text=True, timeout=self.timeout,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        if proc.returncode != 0:
            return None
        return self._parse(proc.stdout)

    def _parse(self, stdout: str) -> Interpretation | None:
        try:
            envelope = json.loads(stdout)
            text = envelope.get("result") if isinstance(envelope, dict) else None
        except json.JSONDecodeError:
            text = stdout
        if not text:
            return None
        obj = _extract_json_object(text)
        if obj is None:
            return None
        try:
            spec = SpecKey(
                kind=str(obj["kind"]).strip().lower(),
                value=str(obj["value"]).strip(),
                package=str(obj["package"]).strip(),
                qualifier=str(obj.get("qualifier") or "").strip(),
            )
        except (KeyError, ValueError, TypeError):
            return None
        env = obj.get("envelope") or {}
        return Interpretation(
            spec=spec,
            envelope={k: v for k, v in env.items() if v not in (None, 0, "")},
            confidence=max(0.0, min(1.0, float(obj.get("confidence") or 0.0))),
            rationale=str(obj.get("rationale") or ""),
        )


def _extract_json_object(text: str) -> dict | None:
    """The model was told 'JSON only', but strip fences/prose defensively."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
