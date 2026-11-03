"""Two worked commissions with invented data, plus the analytical references."""
from __future__ import annotations

import copy

BOARD = {
    "name": "Board in enclosure: two heat sources, vent position",
    "physics": "thermal",
    "domain": {"width": 0.16, "height": 0.10},
    "thickness": 0.0016,
    "material": "fr4_board",
    "face_convection": {"h": 6.0, "t_inf": 40.0, "sides": 2},
    "regions": [
        {"id": "vent", "x0": 0.0, "y0": 0.0, "x1": 0.05, "y1": 0.10,
         "face_convection": {"h": 30.0, "t_inf": 40.0, "sides": 2}},
        {"id": "cpu", "x0": 0.03, "y0": 0.04, "x1": 0.05, "y1": 0.06, "power": 3.0},
        {"id": "regulator", "x0": 0.11, "y0": 0.07, "x1": 0.125, "y1": 0.08, "power": 1.5},
    ],
    "mesh": {"size": 0.004},
    "probes": [{"id": "connector", "x": 0.155, "y": 0.02}],
    "requirements": [{"quantity": "max_temperature", "max": 85.0},
                     {"quantity": "region_avg_temperature:cpu", "max": 80.0}],
}
BOARD_VARIANTS = [
    {"name": "vent over the left third", "changes": {}},
    {"name": "vent in the middle", "changes": {"regions.vent.x0": 0.055, "regions.vent.x1": 0.105}},
    {"name": "vent over the right third", "changes": {"regions.vent.x0": 0.11, "regions.vent.x1": 0.16}},
]

BRACKET = {
    "name": "Equipment bracket: material and thickness",
    "physics": "elastic",
    "domain": {"width": 0.12, "height": 0.06},
    "thickness": 0.005,
    "material": "aluminium_6061_t6",
    "regions": [{"id": "cutout", "x0": 0.04, "y0": 0.02, "x1": 0.085, "y1": 0.04, "void": True}],
    "boundary": [
        {"edge": "left", "type": "fixed", "label": "wall bolts"},
        {"edge": "right", "from": 0.03, "to": 0.06, "type": "force", "fy": -400.0, "label": "equipment"},
    ],
    "gravity": 9.81,
    "mesh": {"size": 0.003},
    "probes": [{"id": "load_point", "x": 0.12, "y": 0.06}],
    "requirements": [{"quantity": "max_displacement", "max": 1.0e-4},
                     {"quantity": "safety_factor", "min": 2.0},
                     {"quantity": "mass", "max": 0.12}],
}
BRACKET_VARIANTS = [
    {"name": f"{label} {t * 1000:.0f} mm", "changes": {"material": mat, "thickness": t}}
    for mat, label in (("steel_s235", "steel"), ("aluminium_6061_t6", "aluminium"))
    for t in (0.003, 0.005, 0.008)
]
BRACKET_SEARCH = {
    "parameters": [{"path": "thickness", "min": 0.002, "max": 0.008, "steps": 7},
                   {"path": "regions.cutout.x1", "values": [0.06, 0.07, 0.08, 0.09, 0.10]}],
    "objective": {"quantity": "mass", "sense": "min"},
    "holdout": [{"name": "25% heavier equipment", "changes": {"boundary.equipment.fy": -500.0}},
                {"name": "side push of 100 N", "changes": {"boundary.equipment.fx": -100.0}}],
    "tradeoff": "max_displacement",
}

EXAMPLES = {
    "board_ventilation": {
        "title": "Which vent layout keeps the board under its temperature limit?",
        "problem": BOARD, "variants": BOARD_VARIANTS,
    },
    "bracket": {
        "title": "Bracket: deformation and mass for several materials and thicknesses",
        "problem": BRACKET, "variants": BRACKET_VARIANTS, "search": BRACKET_SEARCH,
    },
}


def listing():
    return [{"id": k, "title": v["title"], "physics": v["problem"]["physics"],
             "has_search": "search" in v} for k, v in EXAMPLES.items()]


def get(example_id: str) -> dict:
    if example_id not in EXAMPLES:
        raise KeyError(example_id)
    return copy.deepcopy(EXAMPLES[example_id])
