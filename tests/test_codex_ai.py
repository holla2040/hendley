"""CodexCLIInterpreter transport; no test invokes the real Codex service."""

import json
import subprocess

import pytest

from hendley.ai.codex_cli import CodexCLIInterpreter


def test_codex_exec_is_ephemeral_read_only_and_parses_json(monkeypatch):
    seen = []

    def fake_run(cmd, **kw):
        seen.append((cmd, kw))
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"kind": "diode", "value": "10V",
                                       "package": "SOD-323", "qualifier": "zener",
                                       "confidence": 0.9, "rationale": "explicit Z"}),
            stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    got = CodexCLIInterpreter(binary="codex-fake").interpret_part(
        {"designator": "D1", "value": "VZ10", "footprint": "D-SOD323"})

    cmd, kw = seen[0]
    assert cmd[:4] == ["codex-fake", "--ask-for-approval", "never", "exec"]
    assert "--ephemeral" in cmd and cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert cmd[-1] == "-" and kw["input"]
    assert got.spec.qualifier == "zener"


def test_family_read_enables_native_web_search(monkeypatch):
    seen = []
    answer = {"packages": ["SOIC-8"], "partNumbers": ["SP3485EN"],
              "class": "RS-485 transceiver", "traps": [],
              "rationale": "ordering table", "confidence": 0.9}

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(answer), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    got = CodexCLIInterpreter(binary="codex-fake").read_family(
        "SP3485", "IC-SO8", packages=[("SOIC-8", 4)])

    assert "--search" in seen[0]
    assert got["packages"] == ["SOIC-8"]


def test_codex_exec_attaches_each_visual_evidence_image(monkeypatch):
    seen = []

    def fake_run(cmd, **kw):
        seen.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    got = CodexCLIInterpreter(binary="codex-fake")._ask(
        "classify the highlighted symbol",
        images=["/tmp/sheet 1.png", "/tmp/C3-crop.png"],
    )

    assert got == {"ok": True}
    cmd, kw = seen[0]
    assert cmd[cmd.index("exec") + 1:].count("--image") == 2
    assert cmd[cmd.index("--image") + 1] == "/tmp/sheet 1.png"
    second = cmd.index("--image", cmd.index("--image") + 1)
    assert cmd[second + 1] == "/tmp/C3-crop.png"
    assert cmd[-1] == "-" and kw["input"] == "classify the highlighted symbol"


def test_codex_binary_and_model_overrides(monkeypatch):
    monkeypatch.setenv("HENDLEY_CODEX_BIN", "/opt/codex")
    monkeypatch.setenv("HENDLEY_CODEX_MODEL", "gpt-test")
    got = CodexCLIInterpreter()
    assert got.binary == "/opt/codex" and got.model == "gpt-test"


def test_codex_failure_is_an_unavailable_interpreter(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, stdout="", stderr="bad"))
    assert CodexCLIInterpreter(binary="codex-fake").interpret_part(
        {"designator": "D1", "value": "", "footprint": "D-SOD323"}) is None


def test_backend_selection_defaults_to_codex_and_keeps_claude(monkeypatch):
    from hendley.ai.claude_cli import ClaudeCLIInterpreter
    from hendley.app.server import ApiError, _default_interpreter

    monkeypatch.delenv("HENDLEY_INTERPRETER", raising=False)
    assert isinstance(_default_interpreter(), CodexCLIInterpreter)
    monkeypatch.setenv("HENDLEY_INTERPRETER", "claude")
    assert isinstance(_default_interpreter(), ClaudeCLIInterpreter)
    monkeypatch.setenv("HENDLEY_INTERPRETER", "unknown")
    with pytest.raises(ApiError, match="expected 'codex' or 'claude'"):
        _default_interpreter()


def test_app_cli_defaults_to_codex_and_can_select_claude():
    from hendley.cli import build_parser

    parser = build_parser()
    assert parser.parse_args(["app"]).interpreter is None
    assert parser.parse_args(["app", "--interpreter", "codex"]).interpreter == "codex"
    assert parser.parse_args(["app", "--interpreter", "claude"]).interpreter == "claude"
    assert parser.parse_args(
        ["app", "--model", "gpt-5.6-terra"]).model == "gpt-5.6-terra"


def test_startup_description_prints_backend_and_model(monkeypatch):
    from hendley.app.server import interpreter_description

    monkeypatch.setenv("HENDLEY_CODEX_MODEL", "gpt-test")
    assert interpreter_description("codex") == "Codex; model: gpt-test"
    assert interpreter_description(
        "codex", "gpt-5.6-terra") == "Codex; model: gpt-5.6-terra"
    assert interpreter_description("claude") == "Claude; model: CLI default"


def test_model_option_is_not_silently_ignored_for_claude():
    from hendley.app.server import _default_interpreter

    with pytest.raises(ValueError, match="only with Codex"):
        _default_interpreter("claude", "gpt-5.6-terra")
