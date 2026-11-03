import asyncio
import copy

import numpy as np
import pytest
from fastapi.testclient import TestClient

from maxwell import examples
from maxwell.fem import QP, QW, run, shape
from maxwell.model import ProblemError, apply_changes, validate
from maxwell.studies import compare, design_search, reference_cases, refinement, verify_reference


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("MAXWELL_DATA", str(tmp_path))


def test_quadrature_reproduces_closed_form_t6_mass_matrix():
    M = sum(w * np.outer(shape(*q), shape(*q)) for q, w in zip(QP, QW)) / 2  # reference area 1/2
    closed = np.array([[6, -1, -1, 0, -4, 0], [-1, 6, -1, 0, 0, -4], [-1, -1, 6, -4, 0, 0],
                       [0, 0, -4, 32, 16, 16], [-4, 0, 0, 16, 32, 16], [0, -4, 0, 16, 16, 32]]) / 360
    assert np.allclose(M, closed, atol=1e-12)


@pytest.mark.parametrize("case", ["cantilever", "heated_plate", "convective_wall"])
def test_analytical_references_pass(case):
    out = verify_reference(case)
    assert out["ok"], out
    if "changed_condition" in out:
        assert out["changed_condition"]["ok"]


def test_cantilever_tip_deflection_within_half_percent():
    out = verify_reference("cantilever", refine=2)
    tip = next(c for c in out["checks"] if c["quantity"] == "probe:tip:uy")
    assert tip["relative_error"] < 0.005


def test_heated_plate_converges_at_fourth_order():
    p = reference_cases()["heated_plate"]["problem"]
    r = refinement(p, ["probe:centre:temperature"], (1, 2, 4))
    item = r["quantities"]["probe:centre:temperature"]
    assert item["status"] == "converging"
    assert 3.0 < item["observed_order"] < 5.0
    ref = reference_cases()["heated_plate"]["checks"][0]["reference"]
    assert abs(item["extrapolated"] - ref) / ref < 1e-5


def test_clamped_corner_stress_is_reported_as_not_converging():
    p = reference_cases()["cantilever"]["problem"]
    r = refinement(p, ["max_von_mises"], (1, 2, 4))
    assert r["quantities"]["max_von_mises"]["status"].startswith("not converging")


def test_energy_and_force_balance_close():
    t = run(examples.BOARD, field=False)
    assert t["summary"]["heat_balance"]["relative_residual"] < 1e-9
    assert abs(t["summary"]["heat_balance"]["sources_W"] - 4.5) < 1e-9
    e = run(examples.BRACKET, field=False)
    eq = e["summary"]["equilibrium"]
    assert eq["relative_residual"] < 1e-9
    assert eq["applied_fy"] < -400  # load plus self weight


def test_missing_support_becomes_a_question():
    p = copy.deepcopy(examples.BRACKET)
    p["boundary"] = [b for b in p["boundary"] if b["type"] != "fixed"]
    with pytest.raises(ProblemError) as err:
        run(p)
    assert err.value.questions and "held" in err.value.questions[0]


def test_roller_only_support_is_still_a_mechanism():
    p = copy.deepcopy(examples.BRACKET)
    p["boundary"][0]["dofs"] = "y"
    with pytest.raises(ProblemError):
        run(p)


def test_missing_heat_path_becomes_a_question():
    p = copy.deepcopy(examples.BOARD)
    p.pop("face_convection")
    p["regions"][0].pop("face_convection")
    with pytest.raises(ProblemError) as err:
        run(p)
    assert "heat leave" in err.value.questions[0]


def test_disconnected_piece_needs_its_own_support():
    p = copy.deepcopy(examples.BRACKET)
    p["regions"].append({"id": "slot", "x0": 0.09, "y0": 0.0, "x1": 0.1, "y1": 0.06, "void": True})
    with pytest.raises(ProblemError):
        run(p)


def test_missing_material_property_is_asked():
    p = copy.deepcopy(examples.BRACKET)
    p["materials"] = {"mystery": {"E": 1e9}}
    p["material"] = "mystery"
    with pytest.raises(ProblemError) as err:
        validate(p)
    assert "nu" in err.value.questions[0]


def test_board_variants_identify_the_failing_vent():
    ex = examples.get("board_ventilation")
    out = compare(ex["problem"], ex["variants"])
    verdicts = {v["name"]: v["verdict"] for v in out["variants"]}
    assert verdicts["vent over the left third"] == "pass"
    assert verdicts["vent over the right third"] == "fail"
    temps = [v["summary"]["max_temperature"] for v in out["variants"]]
    assert temps[0] < temps[1] < temps[2]


def test_bracket_comparison_trades_mass_against_stiffness():
    ex = examples.get("bracket")
    out = compare(ex["problem"], ex["variants"])
    rows = {v["name"]: v["summary"] for v in out["variants"]}
    assert rows["steel 5 mm"]["mass"] > rows["aluminium 5 mm"]["mass"]
    assert rows["steel 5 mm"]["max_displacement"] < rows["aluminium 5 mm"]["max_displacement"]
    assert "aluminium 5 mm" in out["passing"]


def test_stiffness_scales_with_thickness_and_load():
    base = run(examples.BRACKET, field=False)["summary"]["max_displacement"]
    p = apply_changes(examples.BRACKET, {"gravity": 0.0})
    a = run(p, field=False)["summary"]["max_displacement"]
    b = run(apply_changes(p, {"thickness": 0.010}), field=False)["summary"]["max_displacement"]
    c = run(apply_changes(p, {"boundary.equipment.fy": -800.0}), field=False)["summary"]["max_displacement"]
    assert a < base
    assert abs(b - a / 2) / a < 1e-9
    assert abs(c - 2 * a) / a < 1e-9


def test_design_search_rejects_candidates_that_fail_holdout():
    ex = examples.get("bracket")
    s = ex["search"]
    out = design_search(ex["problem"], s["parameters"], s["objective"], s["holdout"], tradeoff=s["tradeoff"])
    assert out["evaluated"] == 35
    assert out["finalists"][0]["fine_verdict"] == "pass"
    assert not out["finalists"][0]["accepted"]  # cheapest one breaks under the heavier held-out load
    assert out["recommended"]["accepted"]
    assert out["recommended"]["fine_objective"] >= out["finalists"][0]["fine_objective"]
    assert out["frontier_ids"]


def test_design_search_limits():
    ex = examples.get("bracket")
    with pytest.raises(ProblemError):
        design_search(ex["problem"], [], {"quantity": "mass"})
    with pytest.raises(ProblemError):
        design_search(ex["problem"], [{"path": "thickness", "min": 0.001, "max": 0.01, "steps": 100}], {"quantity": "mass"})


def test_paths_address_items_by_id_and_label():
    p = apply_changes(examples.BRACKET, {"regions.cutout.x1": 0.09, "boundary.equipment.fy": -1.0})
    assert p["regions"][0]["x1"] == 0.09 and p["boundary"][1]["fy"] == -1.0
    with pytest.raises(ProblemError):
        apply_changes(examples.BRACKET, {"regions.nothing.x1": 1})


def test_http_api_round_trip():
    from maxwell.app import app
    c = TestClient(app)
    assert c.get("/api/health").json()["service"] == "maxwell-hoard"
    assert "<canvas" in c.get("/").text
    ex = c.get("/api/examples/board_ventilation").json()
    res = c.post("/api/solve", json={"problem": ex["problem"]}).json()
    assert res["status"] == "solved" and res["field"]["values"]["temperature"]
    rec = c.get(f"/api/records/{res['record_id']}").json()
    assert rec["input"]["problem"] == ex["problem"] and "field" not in rec["output"]
    bad = copy.deepcopy(ex["problem"])
    bad.pop("face_convection")
    bad["regions"][0].pop("face_convection")
    r = c.post("/api/solve", json={"problem": bad})
    assert r.status_code == 422 and r.json()["detail"]["questions"]
    assert c.get("/api/records/../../etc").status_code == 404
    v = c.post("/api/references/convective_wall").json()
    assert v["ok"]
    assert c.get("/api/records").json()


def test_mcp_tools_are_listed_without_side_effects(tmp_path):
    from maxwell.mcp_server import mcp
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert {"maxwell_solve", "maxwell_compare", "maxwell_design_search", "maxwell_refinement",
            "maxwell_verify_reference", "maxwell_check", "maxwell_records", "maxwell_examples",
            "maxwell_materials"} <= names
    assert not list((tmp_path / "records").glob("*.json")) if (tmp_path / "records").exists() else True


FIXTURE = __import__("pathlib").Path(__file__).parent / "fixtures" / "plate-hole.stl"


def test_import_vulcan_plate_with_hole():
    """20 x 10 x 5 mm plate with a 4 mm through hole, as generated by Vulcan's CAD."""
    from maxwell.geometry_import import profile_from_stl
    out = profile_from_stl(FIXTURE.read_bytes())
    prof, rep = out["profile"], out["report"]
    assert rep["thin_axis"] == "z" and rep["through_thickness_mismatch"] == 0
    assert abs(prof["domain"]["width"] - 0.02) < 1e-9 and abs(prof["thickness"] - 0.005) < 1e-9
    assert rep["volume_difference"] < 0.01
    void_area = sum((r["x1"] - r["x0"]) * (r["y1"] - r["y0"]) for r in prof["regions"])
    assert abs(void_area - 3.14159265e-6 * 4) / (3.14159265e-6 * 4) < 0.05


def test_imported_profile_solves_with_template_conditions():
    from maxwell import service
    tpl = {"physics": "elastic", "material": "aluminium_6061_t6",
           "boundary": [{"edge": "left", "type": "fixed"}, {"edge": "right", "type": "force", "fx": 1000.0}]}
    out = service.import_stl(FIXTURE.read_bytes(), tpl)
    assert out["status"] == "imported"
    res = run(out["problem"], field=False)
    s = res["summary"]
    net = 1000.0 / ((0.010 - 0.004) * 0.005)
    assert s["equilibrium"]["relative_residual"] < 1e-9
    assert s["max_von_mises"] > net  # the hole concentrates stress above the net-section value


def test_import_refuses_non_prismatic_and_garbage():
    from maxwell.geometry_import import parse_stl, profile_from_stl
    with pytest.raises(ProblemError):
        parse_stl(b"hello world")
    # A step: two boxes of different footprint stacked -> profile changes through the thickness.
    def box(x0, y0, z0, x1, y1, z1):
        v = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], float)
        faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
        return v[np.array(faces)]
    tris = np.concatenate([box(0, 0, 0, 20, 10, 2), box(0, 0, 2, 10, 10, 4)])
    data = b"\0" * 80 + np.uint32(len(tris)).tobytes() + b"".join(np.zeros(3, "<f4").tobytes() + t.astype("<f4").tobytes() + b"\0\0" for t in tris)
    with pytest.raises(ProblemError) as err:
        profile_from_stl(data, thin_axis="z")
    assert "thickness" in str(err.value)


def test_import_endpoint_and_vulcan_unreachable(monkeypatch):
    import base64
    from maxwell.app import app
    c = TestClient(app)
    r = c.post("/api/import", json={"stl_base64": base64.b64encode(FIXTURE.read_bytes()).decode(), "problem": {"physics": "thermal"}})
    assert r.status_code == 200 and r.json()["problem"]["physics"] == "thermal"
    monkeypatch.setenv("VULCAN_URL", "http://127.0.0.1:9")
    r = c.post("/api/import", json={"model_id": "abc"})
    assert r.status_code == 422 and r.json()["detail"]["questions"]


def _box(x0, y0, z0, x1, y1, z1):
    v = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], float)
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    return v[np.array(faces)]


def test_straight_edges_of_imported_profile_are_exact():
    from maxwell.geometry_import import profile_from_stl
    tris = np.concatenate([_box(0, 0, 0, 60, 10, 4), _box(0, 10, 0, 15, 30, 4)])  # L-shaped plate, 4 mm
    data = b"\0" * 80 + np.uint32(len(tris)).tobytes() + b"".join(np.zeros(3, "<f4").tobytes() + t.astype("<f4").tobytes() + b"\0\0" for t in tris)
    out = profile_from_stl(data)
    assert out["profile"]["regions"] == [{"id": "void1", "x0": 0.015, "y0": 0.01, "x1": 0.06, "y1": 0.03, "void": True}]
    assert out["report"]["volume_difference"] < 1e-9


def test_check_catches_missing_supports_without_saving(tmp_path):
    from maxwell import service
    bad = copy.deepcopy(examples.BRACKET)
    bad["boundary"] = [b for b in bad["boundary"] if b["type"] != "fixed"]
    out = service.check(bad)
    assert out["status"] == "needs-input" and out["questions"]
    assert service.check(examples.BRACKET)["status"] == "valid"
    assert service.records() == []


def _fake_vulcan(routes):
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            code, body = routes.get(self.path, (404, b'{"detail":"Unknown studio module"}'))
            self.send_response(code)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_import_from_vulcan_studio_library(monkeypatch):
    import json as _json
    from maxwell.geometry_import import from_vulcan
    stl = FIXTURE.read_bytes()
    srv = _fake_vulcan({"/library/api/models/m42": (200, _json.dumps({"name": "plate", "format": "stl"}).encode()),
                        "/library/api/models/m42/file": (200, stl)})
    try:
        monkeypatch.setenv("VULCAN_URL", f"http://127.0.0.1:{srv.server_address[1]}")
        out = from_vulcan("m42")
        assert out["report"]["source"]["model_id"] == "m42" and out["profile"]["name"] == "plate"
    finally:
        srv.shutdown()


def test_import_from_vulcan_with_library_off_asks_to_switch_it_on(monkeypatch):
    from maxwell.geometry_import import from_vulcan
    srv = _fake_vulcan({"/library/api/models/m42": (409, b'{"error":"module_disabled","module":"library"}')})
    try:
        monkeypatch.setenv("VULCAN_URL", f"http://127.0.0.1:{srv.server_address[1]}")
        with pytest.raises(ProblemError) as err:
            from_vulcan("m42")
        assert "Biblioteca 3D" in err.value.questions[0]
    finally:
        srv.shutdown()
