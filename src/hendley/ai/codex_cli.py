"""Codex CLI interpreter transport for Hendley's structured judgments.

The electronics prompts and strict parsers remain shared with the proven Claude
adapter. Only the non-interactive transport changes: one ephemeral, read-only
``codex exec`` per lazy judgment, authenticated by the user's Codex login.
"""

from __future__ import annotations

import json
import os
import subprocess

from .claude_cli import TIMEOUT_S, ClaudeCLIInterpreter, _extract_json_object

DEFAULT_BIN = "codex"


class CodexCLIInterpreter(ClaudeCLIInterpreter):
    """Interpretation through ephemeral, read-only ``codex exec``."""

    name = "codex-cli"

    def __init__(self, binary: str | None = None, timeout: int = TIMEOUT_S,
                 model: str | None = None):
        # Do not call the parent: its binary override belongs exclusively to
        # Claude and must not accidentally turn a Codex selection back into it.
        self.binary = binary or os.environ.get("HENDLEY_CODEX_BIN", DEFAULT_BIN)
        self.timeout = timeout
        self.model = model or os.environ.get("HENDLEY_CODEX_MODEL") or ""

    def _ask(self, prompt: str, tools: str = "") -> dict | None:
        """Run Codex once and extract the final strict-JSON answer.

        Family judgment is the only path that requests tools; map its existing
        ``WebSearch`` capability onto Codex's native ``--search`` flag. Every
        invocation is ephemeral, non-interactive, and read-only.
        """
        argv = [self.binary, "--ask-for-approval", "never"]
        if tools:
            argv.append("--search")
        argv += ["exec", "--ephemeral", "--sandbox", "read-only",
                 "--color", "never", "--skip-git-repo-check",
                 "--ignore-rules"]
        if self.model:
            argv += ["--model", self.model]
        argv.append("-")
        try:
            proc = subprocess.run(
                argv, input=prompt, capture_output=True, text=True,
                timeout=self.timeout,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        if proc.returncode != 0:
            return None
        text = proc.stdout.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return _extract_json_object(text)
