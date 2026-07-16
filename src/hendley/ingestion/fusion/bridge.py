"""Fusion Electronics HTTP bridge — plain JSON-RPC over HTTP, no MCP client.

Fusion publishes a local HTTP endpoint (Preferences > General > API > "Fusion
MCP Server" — that Autodesk toggle is the only thing here named "MCP"). This
module speaks the verified handshake from ``docs/fusion-notes.md`` ("Talking to
Fusion over HTTP — the full recipe") so a fresh checkout needs no session notes:

- Connect to the **Windows host / WSL gateway IP**, never ``127.0.0.1`` from
  WSL2 (Fusion listens on the Windows loopback; a ``netsh`` port-forward bridges
  it — see README "Reading from Fusion Electronics").
- ...but send ``Host: 127.0.0.1:<port>`` on every request — the server validates
  the ``Host`` header and 403s ("Invalid Host header") on the gateway IP.
- Capture the ``MCP-Session-Id`` **response header** from ``initialize`` and
  resend it on every later request.
- ``POST`` a ``notifications/initialized`` message before any ``tools/call``.
- Initialize exactly once per session; reads return rows as a JSON string in
  ``result.content[0].text`` → ``{"items": [...], "pagination": {...}}``.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request

DEFAULT_PORT = 27182


class BridgeError(RuntimeError):
    """Raised when the Fusion bridge returns an error or an unusable response."""


def _default_gateway() -> str:
    """The Windows host IP as seen from WSL2 = the default route's gateway."""
    out = subprocess.check_output(["ip", "route"], text=True)
    for line in out.splitlines():
        if line.startswith("default"):
            return line.split()[2]
    raise BridgeError("no default gateway found; pass the Fusion host explicitly")


class FusionBridge:
    """One HTTP session to Fusion's local endpoint.

    Host resolution order: explicit ``host`` arg → ``HENDLEY_FUSION_HOST`` env →
    the WSL default-gateway IP. The session id is held in-process and created
    lazily on the first call.
    """

    def __init__(self, host: str | None = None, port: int = DEFAULT_PORT, timeout: int = 60):
        self.host = host or os.environ.get("HENDLEY_FUSION_HOST") or _default_gateway()
        self.url = f"http://{self.host}:{port}/mcp"
        self._loopback = f"127.0.0.1:{port}"  # what the Host header must read as
        self.timeout = timeout
        self._sid: str | None = None

    # -- plumbing ----------------------------------------------------------

    def _post(self, payload: dict, want_headers: bool = False):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Host": self._loopback,
        }
        if self._sid:
            headers["MCP-Session-Id"] = self._sid
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=self.timeout)
        body = resp.read().decode()
        return (resp.headers, body) if want_headers else body

    def _ensure_session(self) -> None:
        if self._sid:
            return
        headers, _ = self._post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "hendley", "version": "1.0"},
                },
            },
            want_headers=True,
        )
        sid = headers.get("MCP-Session-Id") or headers.get("mcp-session-id")
        if not sid:
            raise BridgeError("initialize returned no MCP-Session-Id header")
        self._sid = sid
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call_tool(self, name: str, arguments: dict) -> dict:
        """``tools/call`` → the parsed payload from ``result.content[0].text``."""
        self._ensure_session()
        body = self._post(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        doc = json.loads(body)
        if "error" in doc:
            raise BridgeError(f"bridge error: {doc['error']}")
        return json.loads(doc["result"]["content"][0]["text"])

    # -- the two tools Hendley uses -----------------------------------------

    def read(self, entity_type: str, obj: dict | None = None) -> dict:
        """One ``fusion_mcp_electronics_read`` call (rows come back paginated)."""
        args: dict = {"entity_type": entity_type}
        if obj:
            args["object"] = obj
        return self.call_tool("fusion_mcp_electronics_read", args)

    def read_all(self, entity_type: str, obj: dict | None = None, page: int = 1000) -> list[dict]:
        """Read every row of an entity: loop offsets until an empty batch."""
        items: list[dict] = []
        offset = 0
        for _ in range(100):  # runaway guard
            o = dict(obj or {})
            o["pagination"] = {"limit": page, "offset": offset}
            batch = self.read(entity_type, o).get("items", [])
            if not batch:
                break
            items.extend(batch)
            offset += len(batch)
        return items

    def execute_script(self, py_source: str) -> dict:
        """``fusion_mcp_execute``: run Python (must define ``def run(_context):``) in Fusion.

        Returns the ``{"message", "success"}`` envelope; ``message`` carries the
        script's ``print()`` output.
        """
        return self.call_tool(
            "fusion_mcp_execute", {"featureType": "script", "object": {"script": py_source}}
        )

    def run_eagle(self, command: str) -> dict:
        """Dispatch an EAGLE command into the electronics interpreter.

        Wraps the command in ``Electron.run "…"`` (a bare ``executeTextCommand``
        hits Fusion's *core* channel and fails). ``Electron.run`` returns no
        echo — verify effects out-of-band (see docs/fusion-notes.md).
        """
        if '"' in command:
            raise ValueError(f"EAGLE command may not contain double quotes: {command!r}")
        # The command is embedded in generated Python before Fusion dispatches
        # it. Preserve Windows path separators (notably C:\\Users, whose ``\U``
        # would otherwise be parsed as a Python Unicode escape).
        py_command = command.replace("\\", "\\\\").replace("'", "\\'")
        source = (
            "import adsk.core\n"
            "def run(_context):\n"
            "    app = adsk.core.Application.get()\n"
            f"    app.executeTextCommand('Electron.run \"{py_command}\"')\n"
        )
        return self.execute_script(source)
