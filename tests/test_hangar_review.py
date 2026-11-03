"""Regressions from the independent Hangar review, with physical limiting cases."""
import copy

import pytest

from maxwell.fem import run
from maxwell.model import ProblemError
from maxwell.studies import reference_cases, refinement


def mixed_strength():
    p = copy.deepcopy(reference_cases()["cantilever"]["problem"])
    p["materials"]["ref_steel"]["yield"] = 235e6
    p["materials"]["unknown"] = {"E":200e9,"nu":0.3,"density":7850}
    p["regions"] = [{"id":"left","x0":0,"x1":0.5,"y0":0,"y1":0.1,"material":"unknown"}]
    p["boundary"][1]["fy"] = -1
    return p


@pytest.mark.parametrize("loaded",[False,True])
def test_zero_convection_does_not_anchor_a_temperature(loaded):
    p = copy.deepcopy(reference_cases()["heated_plate"]["problem"])
    if not loaded:
        p["regions"] = []
    p["boundary"] = [{"edge":"left","type":"convection","h":0,"t_inf":20}]
    with pytest.raises(ProblemError,match="undetermined") as error:
        run(p,field=False)
    assert error.value.questions


def test_zero_convection_is_allowed_when_another_condition_anchors_the_body():
    p = copy.deepcopy(reference_cases()["heated_plate"]["problem"])
    p["regions"] = []
    p["boundary"] = [{"edge":"left","type":"convection","h":0,"t_inf":80},
                     {"edge":"right","type":"temperature","value":20}]
    result = run(p,field=False)
    assert result["summary"]["max_temperature"] == pytest.approx(20)


def test_missing_strength_does_not_prevent_displacement_but_has_no_global_factor():
    result = run(mixed_strength(),field=False)
    assert result["summary"]["max_displacement"] > 0
    assert result["summary"]["safety_factor"] is None


def test_a_strength_requirement_asks_for_unknown_material_strength():
    p = mixed_strength()
    p["requirements"] = [{"quantity":"safety_factor","min":2}]
    with pytest.raises(ProblemError,match="yield") as error:
        run(p,field=False)
    assert any("unknown" in q for q in error.value.questions)
    p["materials"]["unknown"]["yield"] = 235e6
    result = run(p,field=False)
    assert result["verdict"] == "pass" and result["summary"]["safety_factor"] > 2


@pytest.mark.parametrize("value",[0,-1,float('nan')])
def test_supplied_material_strength_must_be_finite_and_positive(value):
    p = mixed_strength()
    p["materials"]["unknown"]["yield"] = value
    with pytest.raises(ProblemError,match="yield"):
        run(p,field=False)


@pytest.mark.parametrize("levels",[[1,1],[1,1,1],[1,2,2],[2,1,4]])
def test_refinement_levels_are_strictly_increasing(levels):
    with pytest.raises(ProblemError,match="increasing"):
        refinement(reference_cases()["heated_plate"]["problem"],levels=levels)


def test_different_level_numbers_on_the_same_mesh_do_not_prove_convergence():
    p = copy.deepcopy(reference_cases()["heated_plate"]["problem"])
    p["mesh"]["size"] = 100
    with pytest.raises(ProblemError,match="mesh"):
        refinement(p,levels=[1,2,4])


def test_repeated_solves_in_one_second_keep_both_immutable_records(tmp_path,monkeypatch):
    import datetime
    from maxwell import service
    fixed = datetime.datetime(2026,11,3,tzinfo=datetime.timezone.utc)
    class Clock(datetime.datetime):
        @classmethod
        def now(cls,tz=None): return fixed
    monkeypatch.setenv("MAXWELL_DATA",str(tmp_path))
    monkeypatch.setattr(service.dt,"datetime",Clock)
    p = reference_cases()["convective_wall"]["problem"]
    first = service.solve(p,field=False)
    original = service.record(first["record_id"])
    second = service.solve(p,field=False)
    assert first["record_id"] != second["record_id"]
    assert service.record(first["record_id"]) == original
    assert len(service.records()) == 2


@pytest.fixture
def anyio_backend(): return "asyncio"


@pytest.mark.anyio
async def test_missing_strength_and_duplicate_mesh_levels_through_real_mcp(tmp_path):
    import json, os, sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    root = tmp_path / "mcp"
    params = StdioServerParameters(command=sys.executable,args=["-m","maxwell.mcp_server"],
        env={**os.environ,"MAXWELL_DATA":str(root)})
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            assert len((await session.list_tools()).tools) == 10
            assert not root.exists()
            p = mixed_strength()
            p["requirements"] = [{"quantity":"safety_factor","min":2}]
            result = await session.call_tool("maxwell_solve",{"problem":p})
            assert not result.is_error
            answer = json.loads(next(b.text for b in result.content if b.type=="text"))
            assert answer["status"] == "needs-input" and answer["questions"]
            result = await session.call_tool("maxwell_refinement",{"problem":p,"levels":[1,1,1]})
            assert not result.is_error
            assert json.loads(next(b.text for b in result.content if b.type=="text"))["status"] == "invalid"
