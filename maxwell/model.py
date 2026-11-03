"""Problem description: geometry, materials, conditions and requirements.

Everything is SI: metres, newtons, pascals, watts, kilograms. Temperatures
are in degrees Celsius (the equations are linear, so the offset is harmless).
A problem is plain JSON so it can be stored, diffed and replayed exactly.
"""
from __future__ import annotations

import copy
import math

# Nominal values for first estimates. They are typical datasheet figures,
# not certified properties: every result lists them under assumptions.
MATERIALS: dict[str, dict] = {
    "steel_s235": {"label": "Structural steel S235", "E": 210e9, "nu": 0.30,
                   "density": 7850.0, "k": 50.0, "yield": 235e6},
    "aluminium_6061_t6": {"label": "Aluminium 6061-T6", "E": 69e9, "nu": 0.33,
                          "density": 2700.0, "k": 167.0, "yield": 276e6},
    "copper": {"label": "Copper (annealed)", "E": 117e9, "nu": 0.34,
               "density": 8960.0, "k": 390.0, "yield": 70e6},
    "fr4_board": {"label": "FR-4 board with copper planes (in-plane effective)",
                  "E": 22e9, "nu": 0.15, "density": 1900.0, "k": 18.0,
                  "yield": None},
    "abs": {"label": "ABS plastic", "E": 2.3e9, "nu": 0.35, "density": 1050.0,
            "k": 0.17, "yield": 40e6},
}

PHYSICS = ("thermal", "elastic")
EDGES = ("left", "right", "bottom", "top")
THERMAL_BC = ("temperature", "convection", "flux", "insulated")
ELASTIC_BC = ("fixed", "force", "pressure", "free")
QUANTITIES = (
    "max_temperature", "min_temperature", "max_displacement", "max_abs_ux",
    "max_abs_uy", "max_von_mises", "mass", "safety_factor",
)
PREFIXED = ("region_avg_temperature:", "probe_temperature:", "probe_displacement:",
            "probe_von_mises:")
LIMITS = {"max_dofs": 260_000, "max_cells": 60_000}


class ProblemError(ValueError):
    """Invalid or incomplete problem. `questions` asks for what is missing."""

    def __init__(self, message: str, questions: list[str] | None = None):
        super().__init__(message)
        self.questions = questions or []


def _num(value, name, positive=False, allow_zero=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProblemError(f"{name} must be a number")
    value = float(value)
    if not math.isfinite(value):
        raise ProblemError(f"{name} must be finite")
    if positive and (value < 0 or (value == 0 and not allow_zero)):
        raise ProblemError(f"{name} must be {'> 0' if not allow_zero else '>= 0'}")
    return value


def _sides(v, name):
    if v not in (1, 2, 1.0, 2.0) or isinstance(v, bool):
        raise ProblemError(f"{name} must be 1 or 2")
    return int(v)


def resolve_material(problem: dict, key: str) -> dict:
    custom = problem.get("materials") or {}
    if key in custom:
        base = dict(MATERIALS.get(custom[key].get("base", ""), {}))
        base.update({k: v for k, v in custom[key].items() if k != "base"})
        base.setdefault("label", key)
        return base
    if key in MATERIALS:
        return dict(MATERIALS[key])
    raise ProblemError(f"unknown material '{key}'",
                       [f"What material is '{key}'? Give its properties or pick one of: "
                        + ", ".join(sorted(MATERIALS))])


def validate(problem: dict) -> dict:
    """Return a normalised deep copy, or raise ProblemError with questions."""
    if not isinstance(problem, dict):
        raise ProblemError("problem must be an object")
    p = copy.deepcopy(problem)
    physics = p.get("physics")
    if physics not in PHYSICS:
        raise ProblemError("physics must be 'thermal' or 'elastic'",
                           ["Which physics: steady heat conduction ('thermal') or linear elasticity ('elastic')?"])
    dom = p.get("domain") or {}
    W = _num(dom.get("width"), "domain.width", positive=True, allow_zero=False)
    H = _num(dom.get("height"), "domain.height", positive=True, allow_zero=False)
    p["domain"] = {"width": W, "height": H}
    p["thickness"] = _num(p.get("thickness"), "thickness", positive=True, allow_zero=False)
    mesh = p.get("mesh") or {}
    size = mesh.get("size")
    if size is None:
        size = max(W, H) / 40.0
    size = _num(size, "mesh.size", positive=True, allow_zero=False)
    p["mesh"] = {"size": size}
    if (W / size) * (H / size) > LIMITS["max_cells"]:
        raise ProblemError(f"mesh too fine: about {int(W / size * H / size)} cells, limit {LIMITS['max_cells']}")
    if not p.get("material"):
        raise ProblemError("material is missing", ["Which material is the part made of?"])
    needed = ("k",) if physics == "thermal" else ("E", "nu")
    materials_used = {p["material"]}
    regions = []
    for i, r in enumerate(p.get("regions") or []):
        rid = str(r.get("id") or f"r{i}")
        x0, x1 = sorted((_num(r.get("x0"), f"regions.{rid}.x0"), _num(r.get("x1"), f"regions.{rid}.x1")))
        y0, y1 = sorted((_num(r.get("y0"), f"regions.{rid}.y0"), _num(r.get("y1"), f"regions.{rid}.y1")))
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            raise ProblemError(f"region {rid} has no area")
        x0, x1 = max(0.0, x0), min(W, x1)
        y0, y1 = max(0.0, y0), min(H, y1)
        if x1 <= x0 or y1 <= y0:
            raise ProblemError(f"region {rid} lies outside the domain")
        reg = {"id": rid, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "void": bool(r.get("void"))}
        if r.get("material"):
            reg["material"] = r["material"]
            materials_used.add(r["material"])
        if physics == "thermal":
            if r.get("power") is not None and r.get("q") is not None:
                raise ProblemError(f"region {rid}: give either power (W) or q (W/m3), not both")
            if r.get("power") is not None:
                reg["power"] = _num(r["power"], f"regions.{rid}.power")
            if r.get("q") is not None:
                reg["q"] = _num(r["q"], f"regions.{rid}.q")
            fc = r.get("face_convection")
            if fc:
                reg["face_convection"] = {
                    "h": _num(fc.get("h"), f"regions.{rid}.face_convection.h", positive=True),
                    "t_inf": _num(fc.get("t_inf"), f"regions.{rid}.face_convection.t_inf"),
                    "sides": _sides(fc.get("sides", 2), f"regions.{rid}.face_convection.sides"),
                }
        regions.append(reg)
    if len({r["id"] for r in regions}) != len(regions):
        raise ProblemError("region ids must be unique")
    p["regions"] = regions
    for key in materials_used:
        mat = resolve_material(p, key)
        missing = [n for n in needed if mat.get(n) is None]
        if missing:
            raise ProblemError(f"material {key} lacks {', '.join(missing)}",
                               [f"What is the {n} of {key}?" for n in missing])
        for prop, lo, hi in (("E", 0, None), ("k", 0, None), ("density", -1e-300, None), ("yield", 0, None)):
            v = mat.get(prop)
            if v is not None and (_num(v, f"{key}.{prop}") <= lo):
                raise ProblemError(f"material {key}: {prop} must be > 0")
        if mat.get("nu") is not None and not (-1 < _num(mat["nu"], f"{key}.nu") < 0.5):
            raise ProblemError(f"material {key}: Poisson's ratio must be between -1 and 0.5")
    if physics == "thermal" and p.get("face_convection"):
        fc = p["face_convection"]
        p["face_convection"] = {"h": _num(fc.get("h"), "face_convection.h", positive=True),
                                "t_inf": _num(fc.get("t_inf"), "face_convection.t_inf"),
                                "sides": _sides(fc.get("sides", 2), "face_convection.sides")}
    bcs = []
    allowed = THERMAL_BC if physics == "thermal" else ELASTIC_BC
    for i, b in enumerate(p.get("boundary") or []):
        edge = b.get("edge")
        if edge not in EDGES:
            raise ProblemError(f"boundary {i}: edge must be one of {', '.join(EDGES)}")
        typ = b.get("type")
        if typ not in allowed:
            raise ProblemError(f"boundary {i}: type must be one of {', '.join(allowed)} for {physics}")
        length = H if edge in ("left", "right") else W
        a = _num(b.get("from", 0.0), f"boundary {i}.from")
        c = _num(b.get("to", length), f"boundary {i}.to")
        a, c = sorted((max(0.0, a), min(length, c)))
        if c <= a:
            raise ProblemError(f"boundary {i}: empty segment on {edge}")
        bc = {"edge": edge, "from": a, "to": c, "type": typ, "label": b.get("label") or f"{typ}@{edge}"}
        if typ == "temperature":
            bc["value"] = _num(b.get("value"), f"boundary {i}.value")
        elif typ == "convection":
            bc["h"] = _num(b.get("h"), f"boundary {i}.h", positive=True)
            bc["t_inf"] = _num(b.get("t_inf"), f"boundary {i}.t_inf")
        elif typ == "flux":
            bc["q"] = _num(b.get("q"), f"boundary {i}.q")
        elif typ == "fixed":
            dofs = b.get("dofs", "xy")
            if dofs not in ("x", "y", "xy"):
                raise ProblemError(f"boundary {i}: dofs must be x, y or xy")
            bc["dofs"] = dofs
        elif typ == "force":
            bc["fx"] = _num(b.get("fx", 0.0), f"boundary {i}.fx")
            bc["fy"] = _num(b.get("fy", 0.0), f"boundary {i}.fy")
        elif typ == "pressure":
            bc["p"] = _num(b.get("p"), f"boundary {i}.p")
        bcs.append(bc)
    p["boundary"] = bcs
    if physics == "elastic":
        p["gravity"] = _num(p.get("gravity", 0.0), "gravity")
    probes = []
    for i, pr in enumerate(p.get("probes") or []):
        probes.append({"id": str(pr.get("id") or f"p{i}"),
                       "x": _num(pr.get("x"), f"probes.{i}.x"), "y": _num(pr.get("y"), f"probes.{i}.y")})
    p["probes"] = probes
    reqs = []
    for i, rq in enumerate(p.get("requirements") or []):
        q = rq.get("quantity", "")
        if q not in QUANTITIES and not q.startswith(PREFIXED):
            raise ProblemError(f"requirement {i}: unknown quantity '{q}'")
        item = {"quantity": q}
        for bound in ("max", "min"):
            if rq.get(bound) is not None:
                item[bound] = _num(rq[bound], f"requirements.{i}.{bound}")
        if "max" not in item and "min" not in item:
            raise ProblemError(f"requirement {i}: needs max or min")
        reqs.append(item)
    p["requirements"] = reqs
    p["name"] = str(p.get("name") or "unnamed")
    return p


def set_path(problem: dict, path: str, value):
    """Set a dotted path. List items are addressed by index or by their id."""
    parts = path.split(".")
    node = problem
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if isinstance(node, list):
            if part.isdigit():
                idx = int(part)
                if idx >= len(node):
                    raise ProblemError(f"path {path}: index {idx} out of range")
            else:
                matches = [j for j, item in enumerate(node) if isinstance(item, dict) and str(item.get("id", item.get("label"))) == part]
                if not matches:
                    raise ProblemError(f"path {path}: no item with id '{part}'")
                idx = matches[0]
            if last:
                node[idx] = value
            else:
                node = node[idx]
        elif isinstance(node, dict):
            if last:
                node[part] = value
            else:
                if part not in node or node[part] is None:
                    node[part] = {}
                node = node[part]
        else:
            raise ProblemError(f"path {path}: cannot descend into {type(node).__name__}")
    return problem


def apply_changes(problem: dict, changes: dict) -> dict:
    out = copy.deepcopy(problem)
    for path, value in (changes or {}).items():
        set_path(out, path, copy.deepcopy(value))
    return out
