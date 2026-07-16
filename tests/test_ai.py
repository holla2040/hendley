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


def test_a_part_with_no_value_reads_as_a_spec_with_no_value(monkeypatch):
    # a diode with no schematic VALUE is still fully read: diode, SOD-323.
    # An empty value is the honest answer, never a reason to fabricate one.
    answer = {"kind": "diode", "value": "", "package": "SOD-323",
              "qualifier": "", "envelope": {"mount": "smd", "maxLenMm": 2.7},
              "confidence": 0.9, "rationale": "no value in the design"}
    out = _run_with(monkeypatch,
                    _cli_envelope(json.dumps(answer))).interpret_part(CTX)
    assert out is not None            # None is reserved for "interpreter dead"
    assert out.spec.kind == "diode" and out.spec.package == "SOD-323"
    assert out.spec.value == ""
    assert out.envelope == {"mount": "smd", "maxLenMm": 2.7}


def test_unreadable_package_is_a_partial_not_a_dead_interpreter(monkeypatch):
    # kind read, package not: real knowledge, kept — and the interpreter lives
    answer = {"kind": "diode", "value": "", "package": "", "qualifier": "",
              "confidence": 0.5, "rationale": "can't place the footprint"}
    out = _run_with(monkeypatch,
                    _cli_envelope(json.dumps(answer))).interpret_part(CTX)
    assert out is not None and out.spec is None
    assert out.partial == {"kind": "diode"}


def test_plan_search_shapes_the_query(monkeypatch):
    plan = {"mode": "parametric", "category": "resistors",
            "net": {"package": "0603", "resistance": 22000},
            "sieve": [{"field": "tolerance_fraction", "op": "lte", "value": 0.01},
                      {"field": "bogus"},            # malformed: dropped
                      "junk"],                        # not even a dict: dropped
            "lookingFor": {"kind": "resistor", "value": "22k",
                           "package": "0603", "qualifier": "1%"},
            "say": "22k 0603, 1% or better", "confidence": 3}
    out = _run_with(monkeypatch, _cli_envelope(json.dumps(plan))).plan_search(
        {"designator": "R7", "value": "22k", "footprint": "R-0603",
         "terms": "22k 0603 1%"})
    assert out["mode"] == "parametric" and out["category"] == "resistors"
    assert out["net"] == {"package": "0603", "resistance": 22000}
    assert out["sieve"] == [{"field": "tolerance_fraction", "op": "lte",
                             "value": 0.01}]
    assert out["confidence"] == 1.0          # clamped
    assert out["lookingFor"]["value"] == "22k"


def test_plan_search_rejects_an_unknown_mode(monkeypatch):
    bad = {"mode": "vibes", "category": "resistors"}
    assert _run_with(monkeypatch,
                     _cli_envelope(json.dumps(bad))).plan_search({}) is None


def test_a_sieve_term_carries_the_unit_the_catalog_prints(monkeypatch):
    # the catalog says "50V", not 50 — the agent declares the unit so Python can
    # compare it. Without that, "50 V or better" is uncheckable and every part
    # misses, which is how the engineer gets forced back to exact-match.
    plan = {"mode": "parametric", "category": "capacitors",
            "net": {"package": "SMD,D5xL5.4mm", "capacitance": 1e-5},
            "sieve": [{"field": "Voltage Rating", "op": "gte", "value": 50,
                       "unit": "V"},
                      {"field": "Height - Seated (Max)", "op": "lte",
                       "value": 5.4, "unit": "mm"},
                      {"field": "Diameter", "op": "eq", "value": "5mm"},
                      # no value: it can pass nothing, so it is dropped rather
                      # than left to fail every candidate and blame the catalog
                      {"field": "Tolerance", "op": "eq"},
                      {"field": "Lifetime", "op": "wat", "value": 1}],  # bad op
            "say": "10uF 50V+ electrolytic, D5 x 5.4mm", "confidence": 0.9}
    out = _run_with(monkeypatch, _cli_envelope(json.dumps(plan))).plan_search(
        {"designator": "C4", "value": "10uF", "footprint": "C-E-5",
         "terms": "10uF 50V electrolytic"})
    assert out["sieve"] == [
        {"field": "Voltage Rating", "op": "gte", "value": 50, "unit": "V"},
        {"field": "Height - Seated (Max)", "op": "lte", "value": 5.4,
         "unit": "mm"},
        {"field": "Diameter", "op": "eq", "value": "5mm"}]


def test_derive_key_names_the_requirement(monkeypatch):
    answer = {"spec": {"kind": "Diode", "value": "", "package": "SOD-323",
                       "qualifier": "zener 10V"},
              "rationale": "the engineer searched for a 10V zener",
              "confidence": 0.9}
    out = _run_with(monkeypatch, _cli_envelope(json.dumps(answer))).derive_key(
        {"designator": "D6", "value": "", "footprint": "D-SOD323",
         "terms": "zener 10V SOD-323", "part": {"code": "C1", "mpn": "BZT52C10"}})
    assert out["spec"] == {"kind": "diode", "value": "", "package": "SOD-323",
                           "qualifier": "zener 10V"}   # kind lowercased, no
                                                       # value invented
    assert "zener" in out["rationale"]


def test_derive_key_without_a_package_is_no_key(monkeypatch):
    bad = {"spec": {"kind": "diode", "value": "", "package": ""}}
    assert _run_with(monkeypatch,
                     _cli_envelope(json.dumps(bad))).derive_key({}) is None


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


def test_the_class_note_reaches_the_agent(monkeypatch, tmp_path):
    """Every part class has its own traps and no prompt can carry them all.

    The note for the class in front of the agent is pasted in whole — keyed on
    the CATALOG's own class name, because the index has no honest column for
    what a part IS (its `is_polarized` is false on every electrolytic).
    """
    from hendley.ai.claude_cli import _class_notes

    (tmp_path / "cans.md").write_text(
        "# Cans\n\n```applies-to\n"
        "catalogType: Aluminum Electrolytic Capacitors - SMD\n"
        "category: capacitors\n```\n\n"
        "The can size IS the package string.\n", encoding="utf-8")
    monkeypatch.setenv("HENDLEY_PART_NOTES", str(tmp_path))

    note = _class_notes({"secondType": "Aluminum Electrolytic Capacitors - SMD"})
    assert "The can size IS the package string." in note
    assert "outranks the general rules" in note   # it wins where they disagree

    # the CATALOG's class decides, not a coarse slug: a 0603 MLCC is also
    # "capacitors", and must NOT be handed the electrolytic note
    assert _class_notes({"secondType": "Multilayer Ceramic Capacitors MLCC - SMD/SMT"},
                        "capacitors") == ""
    # with no catalog record to key on, the slug is the honest fallback
    assert "package string" in _class_notes(None, "capacitors")
    # a class nobody has written up gets NOTHING — never a guess
    assert _class_notes({"secondType": "Schottky Diodes"}) == ""


def test_no_notes_directory_is_silence_not_an_error(monkeypatch, tmp_path):
    from hendley.ai.claude_cli import _class_notes

    monkeypatch.setenv("HENDLEY_PART_NOTES", str(tmp_path / "nope"))
    assert _class_notes({"secondType": "Aluminum Electrolytic Capacitors - SMD"}) == ""


def test_the_shipped_electrolytic_note_is_wired_up():
    """The real docs/parts/ note, keyed on the real catalog class string."""
    from hendley.ai.partnotes import note_for

    note = note_for("Aluminum Electrolytic Capacitors - SMD")
    assert note and "SMD,D5xL5.4mm" in note
    assert "is_polarized" in note          # names the poison
    assert "Tolerance" in note             # and the ±20%-rejects-±10% trap


def test_documented_catalog_class_vocabulary_is_available_to_unpinned_reads():
    from hendley.ai.partnotes import catalog_types_for

    types = catalog_types_for()
    assert "Aluminum Electrolytic Capacitors - SMD" in types
    assert "Aluminum Electrolytic Capacitors - Leaded" in types
    assert "Zener Diodes" in types
    assert "Schottky Diodes" in types
    assert "ESD And Surge Protection (TVS/ESD)" in types
    assert "MOSFETs" in types
    assert "Bipolar (BJT)" in types
    assert "JFETs" in types


def test_transistor_note_reaches_unpinned_q_visual_read(monkeypatch):
    seen = {}

    def answer(_self, prompt, **_kwargs):
        seen["prompt"] = prompt
        return {"is": "N-channel MOSFET", "spec": {"kind": "mosfet",
                "value": "N-channel", "package": "SOT-23", "qualifier": ""},
                "search": "N-channel MOSFET", "plan": {"mode": "parametric",
                "category": "mosfets", "net": {"package": "SOT-23"},
                "sieve": []}, "confidence": 0.9}

    monkeypatch.setattr(ClaudeCLIInterpreter, "_ask", answer)
    ClaudeCLIInterpreter().read_part({
        "schematic": {"prefix": "Q"}, "catalog": None})

    assert "FET Type = N-Channel" in seen["prompt"]
    assert "type = NPN" in seen["prompt"]


def test_read_part_can_choose_class_narrowing_keyword_discovery(monkeypatch):
    answer = {
        "is": "10 uF SMD aluminum electrolytic", "search": "10uF aluminum electrolytic",
        "spec": {}, "intent": {"subtype": "aluminum electrolytic"},
        "plan": {"mode": "fts", "category": "components",
                 "net": {"search": "10uF aluminum electrolytic"},
                 "sieve": [{"field": "secondTypeName", "op": "eq",
                            "value": "Aluminum Electrolytic Capacitors - SMD"}]},
        "confidence": 0.8,
    }
    monkeypatch.setattr(ClaudeCLIInterpreter, "_ask", lambda *a, **k: answer)

    got = ClaudeCLIInterpreter().read_part({"catalog": None})

    assert got["plan"]["mode"] == "fts"
    assert got["plan"]["category"] == "components"


def test_part_read_attaches_only_target_crop_and_schematic_sheets(monkeypatch):
    seen = {}

    def answer(_self, _prompt, **kwargs):
        seen.update(kwargs)
        return {"is": "diode", "spec": {"kind": "diode", "value": "",
                "package": "SOD-323", "qualifier": ""}, "search": "diode",
                "plan": {"mode": "parametric", "category": "diodes",
                         "net": {"package": "SOD-323"}, "sieve": []},
                "confidence": 0.8}

    monkeypatch.setattr(ClaudeCLIInterpreter, "_ask", answer)
    ClaudeCLIInterpreter().read_part({"visualEvidence": {
        "designator": "D3",
        "sheets": [{"image": "/tmp/sheet-1.png"},
                   {"image": "/tmp/sheet-2.png"}],
        "boardImage": "/tmp/full-board.png",
        "boardCrops": [{"designator": "C3", "image": "/tmp/C3.png"},
                       {"designator": "D3", "image": "/tmp/D3.png"}],
        "images": ["/tmp/full-board.png", "/tmp/C3.png", "/tmp/D3.png"],
    }})

    assert seen["images"] == [
        "/tmp/D3.png", "/tmp/sheet-1.png", "/tmp/sheet-2.png"]


def test_the_shipped_chip_resistor_note_is_wired_up():
    """The resistor note reaches the agent on the real catalog class string.

    A resistor search that plans without this note re-learns the collision the
    hard way: it states `Resistance = "10kΩ"` alongside `resistance = 10000`
    and rejects all 100 parts.
    """
    from hendley.ai.partnotes import note_for

    note = note_for("Chip Resistor - Surface Mount")
    assert note
    assert "NEVER also state it in the catalog's words" in note
    assert "power_watts" in note           # names the unit-dropped column
    assert "tolerance_fraction" in note    # a FRACTION, and lte


def test_the_zener_note_reaches_diode_interpretation(monkeypatch):
    seen = []
    answer = {"kind": "diode", "value": "10V", "package": "SOD-323",
              "qualifier": "zener", "envelope": {"mount": "smd"},
              "confidence": 0.9, "rationale": "shop alias, engineer confirms"}

    def fake_run(cmd, **kw):
        seen.append(cmd[2])
        return subprocess.CompletedProcess(
            cmd, 0, stdout=_cli_envelope(json.dumps(answer)), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    got = ClaudeCLIInterpreter(binary="claude-fake").interpret_part(
        {"designator": "D9", "value": "VZ10", "footprint": "D-SOD323"})

    assert got.spec.value == "10V" and got.spec.qualifier == "zener"
    assert "VZ10" in seen[0] and "10V0" in seen[0] and "shop conventions" in seen[0]


def test_diode_prompt_carries_deterministic_zener_evidence(monkeypatch):
    seen = []
    answer = {"kind": "diode", "value": "10V", "package": "SOD-323",
              "qualifier": "zener", "confidence": 0.9, "rationale": "explicit Z"}

    def fake_run(cmd, **kw):
        seen.append(cmd[2])
        return subprocess.CompletedProcess(
            cmd, 0, stdout=_cli_envelope(json.dumps(answer)), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ClaudeCLIInterpreter(binary="claude-fake").interpret_part(
        {"designator": "D9", "value": "10V", "footprint": "D-SOD323",
         "attributes": {"TYPE": "Zener"}})
    assert '"zenerEvidence": true' in seen[0]


def test_interpreter_cannot_invent_zener_without_a_z_cue(monkeypatch):
    answer = {"kind": "diode", "value": "1000V", "package": "SOD-323",
              "qualifier": "zener 1000V", "confidence": 0.9,
              "rationale": "misread reverse voltage"}
    out = _run_with(monkeypatch, _cli_envelope(json.dumps(answer))).interpret_part(
        {"designator": "D9", "value": "1000V", "footprint": "D-SOD323",
         "attributes": {}})
    assert out.spec.qualifier == "1000V"
    assert "no Z cue" in out.rationale


def test_the_family_note_is_selected_by_judgment_not_one_boards_class():
    from hendley.ai.partnotes import note_for

    note = note_for(judgment="family")
    assert note and "WORLD knows" in note
