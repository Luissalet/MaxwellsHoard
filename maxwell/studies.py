"""Studies on top of a single solve: analytical references, mesh refinement,
variant comparison and parametric design search with held-out checks."""
from __future__ import annotations

import copy
import itertools
import math

import numpy as np

from .fem import quantity, run
from .model import ProblemError, apply_changes, validate

MAX_RUNS = 80


# ---------------------------------------------------------------- references
def _plate_series(a, b, q, k, x, y, terms=399):
    m = np.arange(1, terms + 1, 2)[:, None]
    n = np.arange(1, terms + 1, 2)[None, :]
    s = np.sin(m * math.pi * x / a) * np.sin(n * math.pi * y / b) / (m * n * ((m / a) ** 2 + (n / b) ** 2))
    return 16 * q / (k * math.pi ** 4) * float(s.sum())


def reference_cases() -> dict:
    """Problems with a closed-form answer, used to check the solver."""
    L, h, t, E, nu, P = 1.0, 0.1, 0.01, 200e9, 0.3, 1000.0
    I, G = t * h ** 3 / 12, E / (2 * (1 + nu))
    beam = {
        "name": "Cantilever beam, end load", "physics": "elastic",
        "domain": {"width": L, "height": h}, "thickness": t, "material": "ref_steel",
        "materials": {"ref_steel": {"E": E, "nu": nu, "density": 7850.0, "label": "reference steel"}},
        "mesh": {"size": h / 4},
        "boundary": [{"edge": "left", "type": "fixed", "label": "wall"},
                     {"edge": "right", "type": "force", "fy": -P, "label": "end load"}],
        "probes": [{"id": "tip", "x": L, "y": h / 2}, {"id": "mid_top", "x": L / 2, "y": h}],
    }
    a, b, k, q = 0.1, 0.1, 15.0, 2e6
    plate = {
        "name": "Square plate, uniform heating, edges at 20 C", "physics": "thermal",
        "domain": {"width": a, "height": b}, "thickness": 0.002, "material": "ref",
        "materials": {"ref": {"k": k, "label": "reference conductor"}},
        "mesh": {"size": a / 8},
        "regions": [{"id": "heated", "x0": 0, "y0": 0, "x1": a, "y1": b, "q": q}],
        "boundary": [{"edge": e, "type": "temperature", "value": 20.0} for e in ("left", "right", "bottom", "top")],
        "probes": [{"id": "centre", "x": a / 2, "y": b / 2}, {"id": "quarter", "x": a / 4, "y": b / 4}],
    }
    Lw, hc, k2, T0, Tinf = 0.05, 40.0, 5.0, 100.0, 20.0
    wall = {
        "name": "Wall, fixed temperature one side, convection the other", "physics": "thermal",
        "domain": {"width": Lw, "height": 0.01}, "thickness": 0.01, "material": "ref",
        "materials": {"ref": {"k": k2, "label": "reference wall"}}, "mesh": {"size": Lw / 5},
        "boundary": [{"edge": "left", "type": "temperature", "value": T0},
                     {"edge": "right", "type": "convection", "h": hc, "t_inf": Tinf}],
        "probes": [{"id": "outer", "x": Lw, "y": 0.005}],
    }
    return {
        "cantilever": {
            "problem": beam,
            "checks": [{"quantity": "probe:tip:uy", "reference": -(P * L ** 3 / (3 * E * I) + P * L / (5 / 6 * G * t * h)),
                        "tolerance": 0.01, "source": "Euler-Bernoulli bending + Timoshenko shear (k=5/6)"},
                       {"quantity": "probe:mid_top:sxx", "reference": 6 * P * (L / 2) / (t * h ** 2),
                        "tolerance": 0.01, "source": "beam bending stress M c / I at mid-span"}],
            "linear_check": {"changes": {"boundary.end load.fy": -2 * P}, "quantity": "probe:tip:uy", "factor": 2.0},
        },
        "heated_plate": {
            "problem": plate,
            "checks": [{"quantity": "probe:centre:temperature", "reference": 20 + _plate_series(a, b, q, k, a / 2, b / 2),
                        "tolerance": 0.002, "source": "double Fourier series, 200x200 odd terms"},
                       {"quantity": "probe:quarter:temperature", "reference": 20 + _plate_series(a, b, q, k, a / 4, b / 4),
                        "tolerance": 0.002, "source": "double Fourier series, 200x200 odd terms"}],
            "linear_check": {"changes": {"regions.heated.q": 2 * q}, "quantity": "probe:centre:temperature", "factor": None,
                             "expected": 20 + 2 * _plate_series(a, b, q, k, a / 2, b / 2)},
        },
        "convective_wall": {
            "problem": wall,
            "checks": [{"quantity": "probe:outer:temperature",
                        "reference": Tinf + (T0 - Tinf) * (1 / hc) / (Lw / k2 + 1 / hc),
                        "tolerance": 1e-6, "source": "series thermal resistances"}],
        },
    }


def _q(result, spec):
    if spec.startswith("probe:"):
        _, pid, field = spec.split(":")
        pr = next(p for p in result["probes"] if p["id"] == pid)
        return pr[field]
    return quantity(result, spec)


def verify_reference(case: str, refine: float = 1.0) -> dict:
    cases = reference_cases()
    if case not in cases:
        raise ProblemError(f"unknown reference case '{case}'; choose one of {', '.join(cases)}")
    c = cases[case]
    res = run(c["problem"], refine=refine, field=False)
    checks = []
    for chk in c["checks"]:
        v = _q(res, chk["quantity"])
        err = abs(v - chk["reference"]) / abs(chk["reference"])
        checks.append({**chk, "value": v, "relative_error": err, "ok": err <= chk["tolerance"]})
    out = {"case": case, "name": c["problem"]["name"], "mesh": res["mesh"], "checks": checks}
    lc = c.get("linear_check")
    if lc:
        res2 = run(apply_changes(c["problem"], lc["changes"]), refine=refine, field=False)
        v1, v2 = _q(res, lc["quantity"]), _q(res2, lc["quantity"])
        if lc.get("factor"):
            expected = v1 * lc["factor"]
        else:
            expected = lc["expected"]
        err = abs(v2 - expected) / abs(expected)
        out["changed_condition"] = {"changes": lc["changes"], "quantity": lc["quantity"], "before": v1, "after": v2,
                                    "expected": expected, "relative_error": err, "ok": err <= 1e-3}
    out["ok"] = all(c_["ok"] for c_ in checks) and out.get("changed_condition", {"ok": True})["ok"]
    return out


# ---------------------------------------------------------------- refinement
def refinement(problem: dict, quantities: list[str] | None = None, levels=(1, 2, 4), reference: dict | None = None) -> dict:
    if len(levels) < 2 or len(levels) > 4:
        raise ProblemError("give between 2 and 4 refinement levels")
    try:
        levels = [float(lv) for lv in levels]
    except (TypeError, ValueError):
        raise ProblemError("refinement levels must be numeric") from None
    if any(not (0 < lv <= 8) for lv in levels) or any(b <= a for a, b in zip(levels, levels[1:])):
        raise ProblemError("refinement levels must be strictly increasing and between 0 and 8")
    p = validate(problem)
    if not quantities:
        quantities = ["max_temperature"] if p["physics"] == "thermal" else ["max_displacement", "max_von_mises"]
    rows = []
    for lv in levels:
        res = run(problem, refine=float(lv), field=False)
        if rows and res["mesh"]["unknowns"] <= rows[-1]["unknowns"]:
            raise ProblemError("refinement levels produce the same mesh; choose levels that increase the mesh resolution")
        rows.append({"refine": lv, "size": res["mesh"]["size"], "unknowns": res["mesh"]["unknowns"],
                     "seconds": res["seconds"], "values": {q: _q(res, q) for q in quantities}})
    report = {}
    for q in quantities:
        vals = [r["values"][q] for r in rows]
        if any(v is None for v in vals):
            raise ProblemError(f"quantity '{q}' is not defined for this problem (missing property, or a probe outside the material)")
        item = {"values": vals, "relative_change_last": abs(vals[-1] - vals[-2]) / max(abs(vals[-1]), 1e-300)}
        if len(vals) >= 3 and levels[-1] / levels[-2] == levels[-2] / levels[-3]:
            r = levels[-1] / levels[-2]
            d1, d2 = vals[-2] - vals[-3], vals[-1] - vals[-2]
            if d1 != 0 and d2 != 0 and d1 * d2 > 0 and abs(d2) < abs(d1):
                order = math.log(abs(d1 / d2)) / math.log(r)
                item["observed_order"] = order
                item["extrapolated"] = vals[-1] + d2 / (r ** order - 1)
                item["estimated_error_last"] = abs(item["extrapolated"] - vals[-1]) / max(abs(item["extrapolated"]), 1e-300)
                item["status"] = "converging"
            elif abs(d2) >= abs(d1) and abs(d2) > 1e-9 * abs(vals[-1]):
                item["status"] = "not converging (singular point or mesh too coarse)"
            else:
                item["status"] = "converged" if abs(d2) <= 1e-9 * max(abs(vals[-1]), 1e-300) else "oscillating"
        if reference and q in reference:
            item["reference"] = reference[q]
            item["errors"] = [abs(v - reference[q]) / abs(reference[q]) for v in vals]
        report[q] = item
    return {"levels": rows, "quantities": report}


# ---------------------------------------------------------------- comparison
def _row(name, changes, res):
    return {"name": name, "changes": changes, "verdict": res["verdict"], "summary": res["summary"],
            "requirements": res["requirements"], "probes": res["probes"], "mesh": res["mesh"]}


def compare(problem: dict, variants: list[dict], refine: float = 1.0) -> dict:
    if not variants:
        raise ProblemError("give at least one variant")
    if len(variants) > 24:
        raise ProblemError("at most 24 variants per comparison")
    validate(problem)
    rows = []
    for i, v in enumerate(variants):
        name = v.get("name") or f"variant {i + 1}"
        changed = apply_changes(problem, v.get("changes") or {})
        try:
            res = run(changed, refine=refine, field=False)
            rows.append(_row(name, v.get("changes") or {}, res))
        except ProblemError as e:
            rows.append({"name": name, "changes": v.get("changes") or {}, "verdict": "needs-input", "error": str(e), "questions": e.questions})
    return {"variants": rows, "passing": [r["name"] for r in rows if r["verdict"] == "pass"],
            "failing": [r["name"] for r in rows if r["verdict"] == "fail"]}


# ---------------------------------------------------------------- inverse design
def _values(param):
    if "values" in param:
        vals = list(param["values"])
    else:
        lo, hi, steps = float(param["min"]), float(param["max"]), int(param.get("steps", 5))
        if steps < 2 or hi <= lo:
            raise ProblemError(f"parameter {param.get('path')}: need min < max and steps >= 2")
        vals = list(np.linspace(lo, hi, steps))
    if not vals:
        raise ProblemError(f"parameter {param.get('path')} has no values")
    return vals


def _frontier(rows, objective, sense, second, second_sense="min"):
    pts = [r for r in rows if r.get("objective") is not None and r.get("second") is not None]
    sg = 1.0 if second_sense == "min" else -1.0
    front = []
    for r in pts:
        dominated = False
        for o in pts:
            better_obj = o["objective"] <= r["objective"] if sense == "min" else o["objective"] >= r["objective"]
            better_sec = sg * o["second"] <= sg * r["second"]
            strictly = (o["objective"] != r["objective"]) or (o["second"] != r["second"])
            if o is not r and better_obj and better_sec and strictly:
                dominated = True
                break
        if not dominated:
            front.append(r["id"])
    return front


def design_search(problem: dict, parameters: list[dict], objective: dict, holdout: list[dict] | None = None,
                  search_refine: float = 1.0, check_refine: float = 2.0, finalists: int = 3,
                  tradeoff: str | None = None) -> dict:
    """Grid search with a cheap mesh, then re-check the best candidates on a
    finer mesh and on load cases that took no part in the search."""
    if not 1 <= len(parameters) <= 3:
        raise ProblemError("use between one and three parameters with physical meaning")
    p0 = validate(problem)
    if not p0["requirements"]:
        raise ProblemError("a design search needs requirements", ["Which limits must the design meet (for example max_displacement, max_temperature, mass)?"])
    obj_q = objective.get("quantity")
    sense = "min" if objective.get("sense", "min") == "min" else "max"
    if not obj_q:
        raise ProblemError("objective.quantity is missing", ["What should the search minimise or maximise (for example mass or max_temperature)?"])
    grids = [_values(prm) for prm in parameters]
    combos = list(itertools.product(*grids))
    if len(combos) > MAX_RUNS:
        raise ProblemError(f"{len(combos)} combinations exceed the limit of {MAX_RUNS}; use fewer steps")
    tradeoff = tradeoff or next((r["quantity"] for r in p0["requirements"] if r["quantity"] != obj_q), None)
    rows = []
    for i, combo in enumerate(combos):
        changes = {prm["path"]: (float(v) if isinstance(v, (int, float, np.floating)) else v) for prm, v in zip(parameters, combo)}
        row = {"id": i, "changes": changes}
        try:
            res = run(apply_changes(problem, changes), refine=search_refine, field=False)
            row.update(verdict=res["verdict"], objective=quantity(res, obj_q),
                       second=quantity(res, tradeoff) if tradeoff else None,
                       requirements=res["requirements"])
        except ProblemError as e:
            row.update(verdict="invalid", error=str(e))
        rows.append(row)
    feasible = [r for r in rows if r["verdict"] == "pass" and r.get("objective") is not None]
    feasible.sort(key=lambda r: r["objective"], reverse=(sense == "max"))
    checked = []
    max_checks = max(int(finalists), 1) + 7
    for r in feasible[:max_checks]:
        if len(checked) >= max(1, int(finalists)) and any(c["accepted"] for c in checked):
            break
        try:
            fine = run(apply_changes(problem, r["changes"]), refine=check_refine, field=False)
        except ProblemError as e:
            checked.append({"id": r["id"], "changes": r["changes"], "search_objective": r["objective"],
                            "fine_objective": None, "fine_verdict": "invalid", "error": str(e), "holdout": [], "accepted": False})
            continue
        entry = {"id": r["id"], "changes": r["changes"], "search_objective": r["objective"],
                 "fine_objective": quantity(fine, obj_q), "fine_verdict": fine["verdict"],
                 "fine_requirements": fine["requirements"], "holdout": []}
        for h in holdout or []:
            try:
                hres = run(apply_changes(apply_changes(problem, r["changes"]), h.get("changes") or {}), refine=check_refine, field=False)
                entry["holdout"].append({"name": h.get("name") or "holdout", "verdict": hres["verdict"], "requirements": hres["requirements"]})
            except ProblemError as e:
                entry["holdout"].append({"name": h.get("name") or "holdout", "verdict": "invalid", "error": str(e)})
        entry["accepted"] = fine["verdict"] == "pass" and all(x["verdict"] == "pass" for x in entry["holdout"])
        checked.append(entry)
    # A requirement with a lower bound (safety factor) means higher is better.
    second_sense = "max" if any(r["quantity"] == tradeoff and "min" in r and "max" not in r for r in p0["requirements"]) else "min"
    front = _frontier(feasible, obj_q, sense, tradeoff, second_sense) if tradeoff else []
    best = next((c for c in checked if c["accepted"]), None)
    return {
        "objective": {"quantity": obj_q, "sense": sense}, "tradeoff_quantity": tradeoff, "tradeoff_sense": second_sense,
        "evaluated": len(rows), "feasible": len(feasible), "candidates": rows,
        "frontier_ids": front, "finalists": checked,
        "recommended": best,
        "note": ("Search used a coarse mesh; finalists were re-solved on a finer mesh and on held-out load cases that "
                 "did not take part in the search; when the cheapest ones fail, further candidates are checked (at most "
                 f"{max(int(finalists), 1) + 7}). The frontier lists feasible trade-offs between the objective and "
                 f"{tradeoff} ({'higher' if second_sense == 'max' else 'lower'} is better), not a single perfect design."),
    }
