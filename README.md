# Maxwell's Hoard

MCP declares examples, materials and coarse problem checking as pure reads (`readOnlyHint=true`), available to Faustus in Plan mode. These helpers create no study data. Solving and saved studies retain their existing persistence; their effects are not relabelled as reads. The combined suite passes66tests, including the real MCP wire contract.

Status: integrated in main and listed in the Hub (explicit start). History: ecosystem1935, corrections1982/1985, family integration1987, icon1995, MCP helpers1999 in the maxwell Ágora space. Native Faustus project1548272a539c is linked to that space.

Family integration1987 adds the canonical Faustus panel and an explicit, port-adaptable Hub launch hint. The panel receives the current problem, variants and search draft, including incomplete JSON, plus the last operation with its exact input and compact result. Editing a draft does not relabel an older result as its calculation. The conversation, model and tools remain in Faustus; Maxwell adds no conversation loop. MCP discovery still starts no HTTP application. Registration and integration remain pending.

Physical engineering for plate-like parts, on your own PC: **steady heat conduction** and **plane-stress linear elasticity** solved with quadratic finite elements, with every condition stated, every result checked against a balance, and a solver that is trusted only as far as its analytical references pass.

Maxwell keeps the geometry, materials, supports, loads, heat sources, mesh and assumptions next to every result, stores the exact input of each study, and turns a missing fact (how the part is held, where the heat leaves) into a concrete question instead of an invisible guess.

## What it does

- **Problem model** (JSON, SI units, °C): rectangular profile with uniform thickness; rectangular regions that change material, are void (openings), carry a heat source (`power` W or `q` W/m³) or a face convection; edge segments with temperature, convection (`h`, `t_inf`), heat flux, clamped/roller supports, total forces or pressure; gravity; probes; requirements (`max_temperature`, `region_avg_temperature:<id>`, `max_displacement`, `max_von_mises`, `safety_factor`, `mass`, probe quantities).
- **Solver**: six-node triangles (T6) on a grid that passes exactly through every region edge and boundary segment; exact degree-4 integration; sparse direct solve. Output: temperature or displacement/von Mises fields, extremes and where they occur, region means, probe values, mass, safety factor against yield, **energy balance** (sources and fluxes in = convection and fixed-temperature heat out) and **force equilibrium** (applied loads + reactions).
- **Missing data become questions**: a part (or a separate piece of it) that can still move as a rigid body, a body with no heat path, a material without the property the physics needs → `needs-input` with the question to ask.
- **Analytical references**: cantilever beam (bending + Timoshenko shear, mid-span bending stress), uniformly heated square plate (double Fourier series), wall with fixed temperature and convection (thermal resistances). Each also changes one condition and checks the response (double the load → double the deflection).
- **Mesh refinement study**: values at ×1, ×2, ×4, observed order, Richardson extrapolation, estimated error, and an explicit warning when a peak keeps growing (re-entrant corners and clamped-edge ends are singular: their stress is not a material prediction).
- **Variant comparison**: `{name, changes: {dotted.path: value}}`; list items are addressed by id or label (`regions.vent.x0`, `boundary.equipment.fy`). Verdicts against the requirements.
- **Design search (inverse design)**: 1–3 parameters with physical meaning, an objective, requirements; grid search on a coarse mesh, then the best feasible candidates are re-solved on a finer mesh **and on held-out load cases that took no part in the search**; returns the accepted recommendation and the feasible trade-off frontier, not a single "perfect" design.
- **Geometry from Vulcan's Hoard**: a constant-thickness STL (a Vulcan model id fetched from its local API, or an uploaded file) becomes the profile; openings become void regions at a stated resolution; volume agreement and through-thickness consistency are reported, and parts whose section changes through the thickness are refused.
- **Records**: every solve and study is saved with its exact input, output and assumptions (`data/records`).

Worked commissions included: *which vent layout keeps a board with two heat sources under 85 °C* (the right-hand vent fails), and *a bracket compared in steel and aluminium at three thicknesses*, plus a search that rejects the lightest bracket because it breaks under a 25 % heavier held-out load.

## Run

```
python -m venv .venv
.venv\Scripts\pip install -e .[test]
.venv\Scripts\python -m maxwell            # http://127.0.0.1:5243
.venv\Scripts\python -m pytest
```

Web page at `/`: problem editor, field map (temperature, displacement, von Mises, exaggerated deformed shape), summary with balances, requirements, probes and assumptions; refinement, comparison and search tables; references; records.

## HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | `{service: "maxwell-hoard"}` |
| GET | `/api/materials` | nominal material library |
| GET | `/api/examples`, `/api/examples/{id}` | worked commissions |
| POST | `/api/check` | validate, questions for missing data |
| POST | `/api/solve` | `{problem, refine, field}` |
| POST | `/api/refinement` | `{problem, quantities, levels}` |
| POST | `/api/compare` | `{problem, variants, refine}` |
| POST | `/api/search` | `{problem, parameters, objective, holdout, finalists, tradeoff}` |
| POST | `/api/import` | `{model_id}` (Vulcan) or `{stl_base64}`, `problem`, `resolution_mm`, `thin_axis` |
| GET/POST | `/api/references`, `/api/references/{case}` | list / verify analytical references |
| GET | `/api/records`, `/api/records/{id}` | saved studies |

Invalid or incomplete problems answer 422 with `{status, error, questions}`.

## MCP (stdio, `python -m maxwell.mcp_server`)

`maxwell_examples`, `maxwell_materials`, `maxwell_check`, `maxwell_solve`, `maxwell_refinement`, `maxwell_compare`, `maxwell_design_search`, `maxwell_verify_reference`, `maxwell_import_geometry`, `maxwell_records`. Listing tools does not solve or write anything.

## Limits (stated, not hidden)

- Two-dimensional: plane stress for elasticity, in-plane conduction for heat (with optional face convection for boards and plates). No 3D solids, fluids, radiation (other than inside a convection coefficient), contact, buckling, plasticity, fatigue, transient or temperature-dependent properties.
- Geometry is rectangles (exact) or a stepped approximation of an imported profile; curved openings raise local peak stresses.
- Material values are nominal datasheet figures; confirm them for real parts. A convergent solver can still solve the wrong problem: the conditions are the engineer's responsibility, which is why they are always shown.
- Pure Python (NumPy/SciPy, BSD licences); no external meshing or solver binaries.

## Corrections awaiting integration (1982)

Zero-convection edges do not determine a temperature: an isolated body asks where heat leaves instead of returning an arbitrary zero. A valid, isothermal zero-flow solution is accepted within a rounding bound derived from the assembled system; the report includes absolute residual, rounding bound and whether relative balance is rounding-limited.

A global safety factor requires yield strength for every material. Without a strength requirement, displacements remain available and the factor is undefined when a material strength is missing. A requested factor asks for the missing strength. Supplied strengths must be finite and positive.

Refinement levels must increase strictly and produce finer meshes. Repeated meshes do not establish convergence. Stored studies have unique IDs and are published atomically, including repeated calculations within one second; old record IDs remain readable.

Validation:51 tests pass, including15 review regressions, real MCP stdio and discovery without creating data. Brave on an isolated instance: zero convection asks for a heat path, a mixed-material beam asks for unknown yield strength, and an anchored zero-flow plate solves uniformly at20°C. These checks use invented cases and analytical references, not measurements of a real part. No models or GPUs were used.

## Constant-thickness geometry correction (1985)

Before sampling an STL profile, every triangle must belong to an end plane or a side parallel to the extrusion axis. Blind pockets, floors and tapered walls are refused even when all three sample sections happen to agree. The report declares coordinate and face-normal tolerances (the latter allows one part per million for float32 STL rounding). Through holes and straight extrusions remain supported. Vertices and requested resolution must be finite; resolution must be positive.

Validation:64 tests pass. An actual box generated by Shannon and Vulcan, previously accepted with a37% volume loss, now asks for a solid3D analysis. A separate120×60×5mm plate with a through opening transfers without volume error. Its displacement converges, while its corner peak stress does not; the refinement report records both outcomes. Reproduction and generated artifacts: `E:/Development/IA/Research/Hangar-2026-11-02/encargo-electronica-cad`.
