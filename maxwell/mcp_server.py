"""MCP tools. Discovery is static: listing tools neither solves nor writes."""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import service

mcp = MCPServer("Maxwell's Hoard")


@mcp.tool()
def maxwell_examples(example_id: str | None = None) -> dict | list:
    """List the worked commissions (board ventilation, bracket) or return one with its problem, variants and search setup."""
    return service.example(example_id) if example_id else service.example_list()


@mcp.tool()
def maxwell_materials() -> list[dict]:
    """Nominal material library (E, nu, density, conductivity k, yield). Values are typical, not certified."""
    return service.materials()


@mcp.tool()
def maxwell_check(problem: dict) -> dict:
    """Validate a problem without solving. Missing supports, materials or heat paths come back as concrete questions."""
    return service.check(problem)


@mcp.tool()
def maxwell_solve(problem: dict, refine: float = 1.0) -> dict:
    """Solve steady heat conduction ('thermal') or plane-stress linear elasticity ('elastic') on a rectangular profile with
    rectangular regions (materials, voids, heat sources, face convection). SI units, temperatures in C.
    Returns summary quantities, probes, requirement verdicts, energy/force balance and the assumptions. A safety-factor
    requirement needs yield strength for every material; zero convection does not anchor temperature. Saved as a record."""
    res = service.solve(problem, refine, field=False)
    return res


@mcp.tool()
def maxwell_refinement(problem: dict, quantities: list[str] | None = None, levels: list[float] | None = None) -> dict:
    """Mesh-refinement study: strictly increasing levels must produce finer meshes. Returns values, observed order,
    extrapolation, and whether a peak is converging or singular; repeated meshes do not establish convergence."""
    return service.study_refinement(problem, quantities, levels or [1, 2, 4])


@mcp.tool()
def maxwell_compare(problem: dict, variants: list[dict], refine: float = 1.0) -> dict:
    """Solve variants of a base problem. Each variant is {name, changes: {dotted.path: value}}; list items are addressed by id
    or label (e.g. 'regions.vent.x0', 'boundary.equipment.fy'). Returns verdicts against the problem requirements."""
    return service.study_compare(problem, variants, refine)


@mcp.tool()
def maxwell_design_search(problem: dict, parameters: list[dict], objective: dict, holdout: list[dict] | None = None,
                          finalists: int = 3, tradeoff: str | None = None) -> dict:
    """Inverse design over 1-3 meaningful parameters ({path, min, max, steps} or {path, values}). Searches on a coarse mesh,
    re-checks the best feasible candidates on a finer mesh and on held-out load cases, and returns a trade-off frontier."""
    return service.study_search(problem, parameters, objective, holdout, 1.0, 2.0, finalists, tradeoff)


@mcp.tool()
def maxwell_verify_reference(case: str | None = None, refine: float = 1.0) -> dict | list:
    """Run an analytical reference (cantilever, heated_plate, convective_wall) and report relative errors; without a case, list them."""
    return service.verify(case, refine) if case else service.references()


@mcp.tool()
def maxwell_import_geometry(model_id: str | None = None, stl_path: str | None = None, problem: dict | None = None,
                            resolution_mm: float | None = None, thin_axis: str | None = None, units: str = "mm") -> dict:
    """Import a constant-thickness part as a Maxwell profile, from a Vulcan's Hoard model id (STL, fetched from its local
    API) or a local STL path. Openings become void regions at the stated resolution; the result merges into `problem`
    (keeping its physics, materials and conditions) and reports volume agreement and through-thickness consistency."""
    if bool(model_id) == bool(stl_path):
        return {"status": "invalid", "error": "give either model_id or stl_path", "questions": []}
    if model_id:
        return service.import_vulcan(model_id, problem, resolution_mm, thin_axis)
    import pathlib
    p = pathlib.Path(stl_path)
    if p.suffix.lower() != ".stl" or not p.is_file():
        return {"status": "invalid", "error": f"{stl_path} is not an existing .stl file", "questions": []}
    return service.import_stl(p.read_bytes(), problem, resolution_mm, thin_axis, units, p.stem)


@mcp.tool()
def maxwell_records(record_id: str | None = None, limit: int = 50) -> dict | list:
    """List saved studies, or read one with its exact input, output and assumptions."""
    if record_id:
        try:
            return service.record(record_id)
        except KeyError:
            return {"status": "invalid", "error": f"unknown record {record_id}"}
    return service.records(limit)


if __name__ == "__main__":
    mcp.run(transport="stdio")
