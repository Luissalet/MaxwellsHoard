"""Operations shared by the HTTP API and the MCP server; every study is stored
with its exact input so it can be replayed and audited."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import uuid

from . import examples
from .fem import run
from .model import MATERIALS, ProblemError, validate
from .studies import compare, design_search, refinement, reference_cases, verify_reference

VERSION = "0.1.0"


def data_dir() -> pathlib.Path:
    d = pathlib.Path(os.environ.get("MAXWELL_DATA") or pathlib.Path(__file__).resolve().parent.parent / "data")
    (d / "records").mkdir(parents=True, exist_ok=True)
    return d


def _strip(result):
    if isinstance(result, dict) and "field" in result:
        result = {k: v for k, v in result.items() if k != "field"}
    return result


def _save(kind: str, inp: dict, out: dict) -> str:
    stamp = dt.datetime.now(dt.timezone.utc)
    digest = hashlib.sha256(json.dumps(inp, sort_keys=True).encode()).hexdigest()[:8]
    rid = f"{stamp:%Y%m%d-%H%M%S}-{kind}-{digest}-{uuid.uuid4().hex}"
    name = (inp.get("problem") or {}).get("name") or inp.get("case") or kind
    rec = {"id": rid, "kind": kind, "name": name, "created": stamp.isoformat(timespec="seconds"),
           "version": VERSION, "input": inp, "output": _strip(out)}
    target = data_dir() / "records" / f"{rid}.json"
    pending = target.with_suffix(".tmp")
    pending.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(pending, target)
    return rid


def _guard(fn):
    try:
        return fn()
    except ProblemError as e:
        return {"status": "needs-input" if e.questions else "invalid", "error": str(e), "questions": e.questions}


def materials():
    return [{"id": k, **v} for k, v in MATERIALS.items()]


def example_list():
    return examples.listing()


def example(example_id: str):
    return examples.get(example_id)


def check(problem: dict):
    def go():
        p = validate(problem)
        # Supports, heat paths and loads on void edges only show up on a mesh:
        # a coarse solve (not saved) catches them before the real one.
        res = run(problem, refine=0.5, field=False)
        return {"status": "valid", "problem": p, "coarse_check": {"mesh": res["mesh"], "verdict": res["verdict"]}}
    return _guard(go)


def solve(problem: dict, refine: float = 1.0, field: bool = True, save: bool = True):
    def go():
        res = run(problem, refine=refine, field=field)
        if save:
            res["record_id"] = _save("solve", {"problem": problem, "refine": refine}, res)
        return res
    return _guard(go)


def study_refinement(problem: dict, quantities=None, levels=(1, 2, 4), save: bool = True):
    def go():
        res = refinement(problem, quantities, tuple(levels))
        res["status"] = "solved"
        if save:
            res["record_id"] = _save("refinement", {"problem": problem, "quantities": quantities, "levels": list(levels)}, res)
        return res
    return _guard(go)


def study_compare(problem: dict, variants: list[dict], refine: float = 1.0, save: bool = True):
    def go():
        res = compare(problem, variants, refine)
        res["status"] = "solved"
        if save:
            res["record_id"] = _save("compare", {"problem": problem, "variants": variants, "refine": refine}, res)
        return res
    return _guard(go)


def study_search(problem: dict, parameters: list[dict], objective: dict, holdout=None, search_refine=1.0,
                 check_refine=2.0, finalists=3, tradeoff=None, save: bool = True):
    def go():
        res = design_search(problem, parameters, objective, holdout, search_refine, check_refine, finalists, tradeoff)
        res["status"] = "solved"
        if save:
            res["record_id"] = _save("search", {"problem": problem, "parameters": parameters, "objective": objective,
                                               "holdout": holdout, "search_refine": search_refine,
                                               "check_refine": check_refine, "finalists": finalists, "tradeoff": tradeoff}, res)
        return res
    return _guard(go)


def references():
    return [{"id": k, "name": v["problem"]["name"], "checks": v["checks"]} for k, v in reference_cases().items()]


def verify(case: str, refine: float = 1.0, save: bool = True):
    def go():
        res = verify_reference(case, refine)
        if save:
            res["record_id"] = _save("reference", {"case": case, "refine": refine}, res)
        return res
    return _guard(go)


def records(limit: int = 100):
    out = []
    for f in sorted((data_dir() / "records").glob("*.json"), reverse=True)[:limit]:
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({k: rec.get(k) for k in ("id", "kind", "name", "created")})
    return out


def record(record_id: str):
    if not re.fullmatch(r"[0-9A-Za-z_-]{1,80}", record_id or ""):
        raise KeyError(record_id)
    f = data_dir() / "records" / f"{record_id}.json"
    if not f.exists():
        raise KeyError(record_id)
    return json.loads(f.read_text(encoding="utf-8"))


def merge_profile(problem: dict | None, profile: dict) -> dict:
    """Put imported geometry into a problem, keeping its physics, materials,
    conditions and non-void regions; previous voids are replaced."""
    import copy as _copy
    out = _copy.deepcopy(problem or {})
    for key in ("domain", "thickness", "mesh"):
        out[key] = _copy.deepcopy(profile[key])
    keep = [r for r in out.get("regions") or [] if not r.get("void")]
    out["regions"] = keep + _copy.deepcopy(profile["regions"])
    out.setdefault("name", profile.get("name"))
    return out


def import_stl(data: bytes, problem: dict | None = None, resolution_mm=None, thin_axis=None, units="mm", name="uploaded STL"):
    from .geometry_import import profile_from_stl

    def go():
        out = profile_from_stl(data, resolution_mm, thin_axis, units, name)
        out["status"] = "imported"
        out["problem"] = merge_profile(problem, out["profile"])
        return out
    return _guard(go)


def import_vulcan(model_id: str, problem: dict | None = None, resolution_mm=None, thin_axis=None):
    from .geometry_import import from_vulcan

    def go():
        out = from_vulcan(model_id, resolution_mm, thin_axis)
        out["status"] = "imported"
        out["problem"] = merge_profile(problem, out["profile"])
        return out
    return _guard(go)
