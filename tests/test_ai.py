"""ClaudeCLIInterpreter — subprocess plumbing and strict-JSON parsing.

The binary is always mocked; no test shells out to a real `claude`.
"""

import json
import subprocess

import pytest

from hendley.ai.claude_cli import ClaudeCLIInterpreter
from hendley.ai.interpreter import Interpretation

CTX = {"designator": "C7", "value": "47u/50V", "footprint": "C-E-5"}

GOOD = {"kind": "capacitor", "value": "47u", "package": "C-E-5",
        "qualifier": "50V",
        "envelope": {"mount": "tht", "maxDiaMm": 10, "leadSpacingMm": 5},
        "confidence": 0.92,
        "rationale": "C prefix + 47u/50V on an electrolytic 5mm footprint"}


def _cli_envelope(text: str) -> str:
    """What `claude -p --output-format json` prints: an envelope with result."""
    return json.dumps({"type": "result", "result": text})


def _run_with(monkeypatch, stdout: str, returncode: int = 0):
    def fake_run(cmd, **kw):
        assert cmd[1] == "-p" and cmd[-2:] == ["--output-format", "json"]
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    return ClaudeCLIInterpreter(binary="claude-fake")


def test_happy_path_strict_json(monkeypatch):
    it = _run_with(monkeypatch, _cli_envelope(json.dumps(GOOD)))
    out = it.interpret_part(CTX)
    assert out.spec.kind == "capacitor" and out.spec.value == "47u"
    assert out.spec.package == "C-E-5" and out.spec.qualifier == "50V"
    assert out.envelope["leadSpacingMm"] == 5
    assert out.confidence == 0.92 and "electrolytic" in out.rationale


def test_code_fences_and_prose_are_tolerated(monkeypatch):
    text = "Here you go:\n```json\n" + json.dumps(GOOD) + "\n```"
    out = _run_with(monkeypatch, _cli_envelope(text)).interpret_part(CTX)
    assert out is not None and out.spec.value == "47u"


def test_garbage_output_returns_none(monkeypatch):
    assert _run_with(monkeypatch, _cli_envelope("I cannot help")).interpret_part(CTX) is None
    assert _run_with(monkeypatch, "not json at all").interpret_part(CTX) is None
    assert _run_with(monkeypatch, "", returncode=1).interpret_part(CTX) is None


def test_incomplete_spec_returns_none(monkeypatch):
    bad = dict(GOOD, value="")  # SpecKey requires kind/value/package
    assert _run_with(monkeypatch, _cli_envelope(json.dumps(bad))).interpret_part(CTX) is None


def test_missing_binary_and_timeout_return_none(monkeypatch):
    def raise_fnf(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(subprocess, "run", raise_fnf)
    assert ClaudeCLIInterpreter(binary="nope").interpret_part(CTX) is None

    def raise_timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert ClaudeCLIInterpreter().interpret_part(CTX) is None


def test_confidence_clamped_and_envelope_cleaned(monkeypatch):
    weird = dict(GOOD, confidence=7,
                 envelope={"mount": "tht", "maxDiaMm": 0, "maxLenMm": None})
    out = _run_with(monkeypatch, _cli_envelope(json.dumps(weird))).interpret_part(CTX)
    assert out.confidence == 1.0
    assert out.envelope == {"mount": "tht"}  # zero/None fields dropped


def test_interpretation_roundtrip():
    out = Interpretation.from_dict(
        Interpretation.from_dict({"spec": GOOD | {}, "envelope": GOOD["envelope"],
                                  "confidence": 0.9, "rationale": "x"}
                                 | {"spec": {"kind": "capacitor", "value": "47u",
                                             "package": "C-E-5"}}).to_dict())
    assert out.spec.package == "C-E-5" and out.confidence == 0.9


def test_env_binary_override(monkeypatch):
    monkeypatch.setenv("HENDLEY_CLAUDE_BIN", "/opt/claude")
    assert ClaudeCLIInterpreter().binary == "/opt/claude"
    with pytest.raises(TypeError):
        ClaudeCLIInterpreter(binary="x").interpret_part()  # ctx is required
