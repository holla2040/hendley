"""Host selection for the Fusion bridge — all offline (probes are faked)."""

import types

import pytest

import hendley.ingestion.fusion.bridge as bridge_mod
from hendley.ingestion.fusion.bridge import BridgeError, FusionBridge, default_host


@pytest.fixture
def probes(monkeypatch):
    """Fake the TCP probe: hosts in ``up`` answer, everything else refuses."""
    up: set[str] = set()
    seen: list[tuple[str, int]] = []

    def fake(host, port, timeout):
        seen.append((host, port))
        return host in up

    monkeypatch.setattr(bridge_mod, "_port_answers", fake)
    monkeypatch.delenv("HENDLEY_FUSION_HOST", raising=False)
    return up, seen


def _no_gateway_lookup(*_a, **_k):
    raise AssertionError("the WSL gateway must not be looked up here")


def test_explicit_host_wins_without_probing(probes, monkeypatch):
    _, seen = probes
    monkeypatch.setenv("HENDLEY_FUSION_HOST", "10.0.0.9")
    bridge = FusionBridge(host="192.168.1.5")
    assert bridge.host == "192.168.1.5" and seen == []


def test_env_host_beats_the_probe(probes, monkeypatch):
    _, seen = probes
    monkeypatch.setenv("HENDLEY_FUSION_HOST", "10.0.0.9")
    assert FusionBridge().url == "http://10.0.0.9:27182/mcp"
    assert seen == []


def test_loopback_first_when_it_answers(probes, monkeypatch):
    up, _ = probes
    up.add("127.0.0.1")
    monkeypatch.setattr(bridge_mod, "running_under_wsl", lambda: True)
    monkeypatch.setattr(bridge_mod, "_default_gateway", _no_gateway_lookup)
    assert default_host() == "127.0.0.1"


def test_probe_uses_the_requested_port(probes):
    up, seen = probes
    up.add("127.0.0.1")
    assert FusionBridge(port=28000).url == "http://127.0.0.1:28000/mcp"
    assert seen == [("127.0.0.1", 28000)]


def test_wsl_falls_back_to_the_gateway(probes, monkeypatch):
    up, seen = probes
    up.add("172.17.64.1")
    monkeypatch.setattr(bridge_mod, "running_under_wsl", lambda: True)
    monkeypatch.setattr(bridge_mod, "_default_gateway", lambda: "172.17.64.1")
    bridge = FusionBridge()
    assert bridge.host == "172.17.64.1"
    assert seen == [("127.0.0.1", 27182), ("172.17.64.1", 27182)]


def test_native_never_tries_the_gateway(probes, monkeypatch):
    monkeypatch.setattr(bridge_mod, "running_under_wsl", lambda: False)
    monkeypatch.setattr(bridge_mod, "_default_gateway", _no_gateway_lookup)
    with pytest.raises(BridgeError) as err:
        default_host()
    msg = str(err.value)
    assert "127.0.0.1:27182" in msg and "Fusion MCP Server" in msg
    assert "port-forward" not in msg


def test_wsl_with_nothing_reachable_is_a_bridge_error(probes, monkeypatch):
    monkeypatch.setattr(bridge_mod, "running_under_wsl", lambda: True)
    monkeypatch.setattr(bridge_mod, "_default_gateway", lambda: "172.17.64.1")
    with pytest.raises(BridgeError) as err:
        default_host()
    assert "172.17.64.1:27182" in str(err.value)
    assert "port-forward" in str(err.value)


def test_wsl_without_a_default_route_is_a_bridge_error(probes, monkeypatch):
    monkeypatch.setattr(bridge_mod, "running_under_wsl", lambda: True)
    monkeypatch.setattr(bridge_mod, "_default_gateway", lambda: None)
    with pytest.raises(BridgeError, match="no default route"):
        default_host()


def test_missing_ip_binary_is_not_a_raw_file_not_found(monkeypatch):
    def boom(*_a, **_k):
        raise FileNotFoundError("ip")

    monkeypatch.setattr(bridge_mod.subprocess, "run", boom)
    assert bridge_mod._default_gateway() is None


def test_gateway_parsed_from_ip_route(monkeypatch):
    class Done:
        stdout = "default via 172.17.64.1 dev eth0 proto kernel\n172.17.64.0/20 dev eth0\n"

    monkeypatch.setattr(bridge_mod.subprocess, "run", lambda *a, **k: Done())
    assert bridge_mod._default_gateway() == "172.17.64.1"


def test_wsl_detection(monkeypatch):
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.delenv("WSL_INTEROP", raising=False)
    monkeypatch.setattr(bridge_mod.sys, "platform", "linux")
    monkeypatch.setattr(bridge_mod.platform, "release",
                        lambda: "5.15.167.4-microsoft-standard-WSL2")
    assert bridge_mod.running_under_wsl()
    monkeypatch.setattr(bridge_mod.platform, "release", lambda: "6.8.0-45-generic")
    assert not bridge_mod.running_under_wsl()
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert bridge_mod.running_under_wsl()
    for native in ("win32", "darwin"):
        monkeypatch.setattr(bridge_mod.sys, "platform", native)
        assert not bridge_mod.running_under_wsl()


def test_host_header_reads_loopback_on_every_request(monkeypatch):
    """The spoofed Host header is what lets the WSL gateway path through."""
    sent = []

    class Resp:
        headers = types.MappingProxyType({"MCP-Session-Id": "sid-1"})

        def read(self):
            return b'{"result": {"content": [{"text": "{\\"items\\": []}"}]}}'

    def fake_urlopen(req, timeout):
        sent.append((req.full_url, req.get_header("Host"), req.get_header("Mcp-session-id")))
        return Resp()

    monkeypatch.setattr(bridge_mod.urllib.request, "urlopen", fake_urlopen)
    bridge = FusionBridge(host="172.17.64.1")
    assert bridge.read("electronics.Part") == {"items": []}
    assert [s[0] for s in sent] == ["http://172.17.64.1:27182/mcp"] * 3
    assert {s[1] for s in sent} == {"127.0.0.1:27182"}
    assert [s[2] for s in sent] == [None, "sid-1", "sid-1"]
