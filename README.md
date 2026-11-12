# Maxwell's Hoard

Local physical engineering for plate-like parts: steady heat conduction and plane-stress elasticity with finite elements. [Español](README.es.md)

![Maxwell's Hoard](app-icon.png)

## What it is

Maxwell's Hoard solves physical engineering problems for plate-like parts on your own PC: **steady heat conduction** and **plane-stress linear elasticity** solved with quadratic finite elements, with every condition stated, every result checked against a balance, and a solver that is trusted only as far as its analytical references pass.

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
- **Refusals instead of guesses**: a body with no path for heat to leave asks where it leaves instead of returning an arbitrary zero; a safety factor needs the yield strength of every material; refinement levels must strictly increase; imported profiles with blind pockets, floors or tapered walls are refused.
- **Records**: every solve and study is saved with its exact input, output and assumptions (`data/records`).

Worked examples included: *which vent layout keeps a board with two heat sources under 85 °C* (the right-hand vent fails), and *a bracket compared in steel and aluminium at three thicknesses*, plus a search that rejects the lightest bracket because it breaks under a 25 % heavier held-out load.

## Run

Requires Python 3.11 or later.

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

## Limits

- Two-dimensional: plane stress for elasticity, in-plane conduction for heat (with optional face convection for boards and plates). No 3D solids, fluids, radiation (other than inside a convection coefficient), contact, buckling, plasticity, fatigue, transient or temperature-dependent properties.
- Geometry is rectangles (exact) or a stepped approximation of an imported profile; curved openings raise local peak stresses.
- Material values are nominal datasheet figures; confirm them for real parts. A convergent solver can still solve the wrong problem: the conditions are the engineer's responsibility, which is why they are always shown.
- Pure Python (NumPy/SciPy, BSD licences); no external meshing or solver binaries.

## Connection with Faustus and Hoard Hub

`faustus-plugin.json` registers the app as a Faustus plugin. The Hub starts the web application explicitly, on a port that adapts if the default is taken. Faustus gets a panel that shows the current problem, its variants and the search draft (including incomplete JSON) together with the last operation, its exact input and its compact result; the conversation, model and tools stay in Faustus.

MCP (stdio, `python -m maxwell.mcp_server`) exposes ten tools and starts no HTTP application. Listing tools solves nothing and writes nothing.

| Group | Tools |
| --- | --- |
| Pure reads (read-only hint, usable in Faustus Plan mode) | `maxwell_examples`, `maxwell_materials`, `maxwell_check` |
| Solving and studies | `maxwell_solve`, `maxwell_refinement`, `maxwell_compare`, `maxwell_design_search` |
| References and geometry | `maxwell_verify_reference`, `maxwell_import_geometry` |
| Records | `maxwell_records` |

The app also carries procedures from the family's skill library for connecting agents (`plate-thermal-stress-check`, `measured-improvement`, `verification-loop`). They are named in what an agent reads on connecting, read with `skills_list` and `skill_read`, searched and assigned with `skills_library` and `skills_assign`, and offered as prompts. They are chosen on the skills page (`/api/agent/skills/page`) or in the Hub's Skills tab.

## Project layout

| Path | Contents |
| --- | --- |
| `maxwell/fem.py`, `model.py` | Finite-element solver and problem model |
| `maxwell/studies.py`, `service.py` | Refinement, comparison, design search and records |
| `maxwell/geometry_import.py` | STL profile import |
| `maxwell/app.py`, `static/` | HTTP API and web page |
| `maxwell/mcp_server.py` | MCP server |
| `maxwell/hoard_link/` | Shared Hoard family code |
| `tests/` | Test suite |
| `data/records/` | Saved studies |
| `docs/` | Research notes (Spanish) |

## Credits

Pure Python on NumPy and SciPy (BSD licences); no external meshing or solver binaries.
