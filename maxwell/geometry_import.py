"""Turn a constant-thickness solid (an STL from Vulcan's Hoard or any other
source) into a Maxwell profile: outer rectangle, thickness and void regions.

The solid is sampled on a grid in its plane at mid-thickness (ray parity
along the thin axis). Openings become rectangular void regions, so curved
edges are approximated by steps of one sampling cell; the report states the
resolution and how far the profile area times thickness is from the true
volume. Parts whose profile changes through the thickness are refused.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import urllib.error
import urllib.request

import numpy as np

from .model import ProblemError

MAX_TRIANGLES = 400_000
MAX_SAMPLES = 40_000


def parse_stl(data: bytes) -> np.ndarray:
    """Triangles (n, 3, 3) from binary or ASCII STL."""
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if 84 + 50 * n == len(data):
            if n > MAX_TRIANGLES:
                raise ProblemError(f"mesh has {n} triangles, limit {MAX_TRIANGLES}")
            rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n, offset=84)
            return rec["v"].astype(float)
    text = data.decode("ascii", errors="replace")
    if "vertex" not in text:
        raise ProblemError("not an STL file (binary size mismatch and no ASCII vertices)")
    try:
        verts = [list(map(float, line.split()[1:4])) for line in text.splitlines() if line.strip().startswith("vertex")]
    except ValueError:
        raise ProblemError("ASCII STL with an unreadable vertex")
    if any(len(v) != 3 for v in verts):
        raise ProblemError("ASCII STL with an incomplete vertex")
    if len(verts) % 3 or not verts:
        raise ProblemError("ASCII STL with an incomplete triangle")
    if len(verts) // 3 > MAX_TRIANGLES:
        raise ProblemError(f"mesh has {len(verts) // 3} triangles, limit {MAX_TRIANGLES}")
    return np.array(verts).reshape(-1, 3, 3)


def _inside(tris2, wv, us, vs, level):
    """Parity of crossings above `level` along +w for every (u, v) sample."""
    count = np.zeros((len(vs), len(us)), int)
    du = us[1] - us[0] if len(us) > 1 else 1.0
    dv = vs[1] - vs[0] if len(vs) > 1 else 1.0
    for (a, b, c), (wa, wb, wc) in zip(tris2, wv):
        det = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
        if abs(det) < 1e-14:
            continue
        lo_u, hi_u = min(a[0], b[0], c[0]), max(a[0], b[0], c[0])
        lo_v, hi_v = min(a[1], b[1], c[1]), max(a[1], b[1], c[1])
        i0 = max(0, int(np.ceil((lo_u - us[0]) / du)))
        i1 = min(len(us) - 1, int(np.floor((hi_u - us[0]) / du)))
        j0 = max(0, int(np.ceil((lo_v - vs[0]) / dv)))
        j1 = min(len(vs) - 1, int(np.floor((hi_v - vs[0]) / dv)))
        if i1 < i0 or j1 < j0:
            continue
        U, V = np.meshgrid(us[i0:i1 + 1], vs[j0:j1 + 1])
        l2 = ((U - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (V - a[1])) / det
        l3 = ((b[0] - a[0]) * (V - a[1]) - (U - a[0]) * (b[1] - a[1])) / det
        l1 = 1 - l2 - l3
        hit = (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
        w = l1 * wa + l2 * wb + l3 * wc
        count[j0:j1 + 1, i0:i1 + 1] += hit & (w > level)
    return count % 2 == 1


def _rectangles(void, us_edges, vs_edges):
    """Merge void samples into rectangles: runs per row, stacked while identical."""
    rects, open_ = [], {}
    for j in range(void.shape[0] + 1):
        runs = set()
        if j < void.shape[0]:
            row = void[j]
            i = 0
            while i < len(row):
                if row[i]:
                    k = i
                    while k + 1 < len(row) and row[k + 1]:
                        k += 1
                    runs.add((i, k))
                    i = k + 1
                else:
                    i += 1
        for run in list(open_):
            if run not in runs:
                j0 = open_.pop(run)
                rects.append((us_edges[run[0]], vs_edges[j0], us_edges[run[1] + 1], vs_edges[j]))
        for run in runs:
            open_.setdefault(run, j)
    return rects


def profile_from_stl(data: bytes, resolution_mm: float | None = None, thin_axis: str | None = None,
                     units: str = "mm", name: str = "imported part") -> dict:
    tris = parse_stl(data)
    scale = {"mm": 1e-3, "m": 1.0, "in": 0.0254}.get(units)
    if scale is None:
        raise ProblemError("units must be mm, m or in")
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    ext = hi - lo
    axes = "xyz"
    t_ax = axes.index(thin_axis) if thin_axis else int(np.argmin(ext))
    plane = [a for a in range(3) if a != t_ax]
    if ext[t_ax] <= 0 or min(ext[plane]) <= 0:
        raise ProblemError("the mesh is flat in more than one direction")
    res = resolution_mm if resolution_mm else min(ext[plane]) / 40.0
    nu, nv = int(np.ceil(ext[plane[0]] / res)), int(np.ceil(ext[plane[1]] / res))
    if nu * nv > MAX_SAMPLES:
        raise ProblemError(f"{nu * nv} samples exceed {MAX_SAMPLES}; use a coarser resolution")
    du, dv = ext[plane[0]] / nu, ext[plane[1]] / nv
    jitter = 1e-7 * (1 + np.sqrt(2))
    us = lo[plane[0]] + du * (np.arange(nu) + 0.5) + jitter * du
    vs = lo[plane[1]] + dv * (np.arange(nv) + 0.5) + jitter * np.sqrt(3) * dv
    tris2, wv = tris[:, :, plane], tris[:, :, t_ax]
    levels = [lo[t_ax] + f * ext[t_ax] for f in (0.5, 0.2, 0.8)]
    mid, low, high = (_inside(tris2, wv, us, vs, lv) for lv in levels)
    mismatch = float(((mid != low) | (mid != high)).mean())
    if mismatch > 0.02:
        raise ProblemError(f"the profile changes through the thickness in {mismatch:.1%} of the samples: "
                           "this is not a constant-thickness plate",
                           ["Which section should be analysed? Give the thin axis or a plate-like part."])
    if not mid.any():
        raise ProblemError("no material found at mid-thickness (open or inverted mesh?)")
    # Volume from the mesh (divergence theorem) to check the profile.
    v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
    volume = abs(float(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum() / 6))
    area = float(mid.sum()) * du * dv
    u_edges = np.concatenate([[0.0], (np.arange(1, nu + 1)) * du])
    v_edges = np.concatenate([[0.0], (np.arange(1, nv + 1)) * dv])
    # Snap each opening edge to a real vertex coordinate within half a sample:
    # straight edges of the part come out exact instead of off by up to one step.
    cu = np.unique(np.round(tris[:, :, plane[0]].ravel() - lo[plane[0]], 9))
    cv = np.unique(np.round(tris[:, :, plane[1]].ravel() - lo[plane[1]], 9))

    def snap(edges, coords, step):
        out = edges.copy()
        for k in range(1, len(edges) - 1):
            near = coords[np.abs(coords - edges[k]) <= step / 2 + 1e-12]
            # Keep the edges strictly increasing: a vertex at a sample centre
            # must not collapse two neighbouring edges into one.
            near = near[(near > out[k - 1] + 1e-9) & (near < edges[k + 1] - 1e-9)]
            if len(near):
                out[k] = near[np.argmin(np.abs(near - edges[k]))]
        return out

    u_edges, v_edges = snap(u_edges, cu, du), snap(v_edges, cv, dv)
    rects = [r for r in _rectangles(~mid, u_edges * scale, v_edges * scale) if r[2] > r[0] and r[3] > r[1]]
    area = float(sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects)) / scale ** 2
    area = ext[plane[0]] * ext[plane[1]] - area
    regions = [{"id": f"void{i + 1}", "x0": round(float(r[0]), 9), "y0": round(float(r[1]), 9),
                "x1": round(float(r[2]), 9), "y1": round(float(r[3]), 9), "void": True} for i, r in enumerate(rects)]
    W, H, t = ext[plane[0]] * scale, ext[plane[1]] * scale, ext[t_ax] * scale
    profile = {"name": name, "domain": {"width": round(float(W), 9), "height": round(float(H), 9)},
               "thickness": round(float(t), 9), "regions": regions, "mesh": {"size": round(float(max(du, dv) * scale), 9)}}
    report = {
        "sha256": hashlib.sha256(data).hexdigest(), "triangles": int(len(tris)),
        "thin_axis": axes[t_ax], "profile_axes": [axes[plane[0]], axes[plane[1]]],
        "bbox": [float(e * scale) for e in ext], "resolution": [float(du * scale), float(dv * scale)],
        "void_rectangles": len(regions), "through_thickness_mismatch": mismatch,
        "mesh_volume": volume * scale ** 3, "profile_volume": area * ext[t_ax] * scale ** 3,
        "notes": [f"Curved edges are approximated by steps of {du:.3g} x {dv:.3g} {units}.",
                  "Stepped edges add artificial corners: peak stresses next to curved openings are overestimated; temperatures, displacements and mass are not affected the same way.",
                  "Openings at the outer boundary are voids touching the edge; the outer rectangle is the bounding box.",
                  "Add material, supports, loads or heat sources before solving: geometry alone is not an analysis."],
    }
    report["volume_difference"] = abs(report["profile_volume"] - report["mesh_volume"]) / max(report["mesh_volume"], 1e-30)
    return {"profile": profile, "report": report}


def vulcan_url() -> str:
    return os.environ.get("VULCAN_URL", "http://127.0.0.1:5186").rstrip("/")


def _get(url, limit=None):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read(limit) if limit else r.read()


def from_vulcan(model_id: str, resolution_mm: float | None = None, thin_axis: str | None = None) -> dict:
    """Fetch a model from Vulcan's Hoard. The studio serves its library module
    under /library; older single-app versions served /api/models directly."""
    if not str(model_id).replace("-", "").replace("_", "").isalnum():
        raise ProblemError("invalid model id")
    base = vulcan_url()
    info = data = None
    for prefix in ("/library", ""):
        try:
            info = json.loads(_get(f"{base}{prefix}/api/models/{model_id}").decode("utf-8"))
            data = _get(f"{base}{prefix}/api/models/{model_id}/file", 64 * 1024 * 1024)
            break
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 409 and "module_disabled" in body:
                raise ProblemError("the 3D library module of Vulcan's Hoard is switched off",
                                   ["Switch on the «Biblioteca 3D» module in Vulcan's Hoard, or upload the STL directly."])
            if e.code == 404 and prefix and "Unknown studio module" in body:
                continue  # older Vulcan without the studio: try the plain path
            raise ProblemError(f"Vulcan answered {e.code} for model {model_id}: {body[:200]}")
        except (urllib.error.URLError, OSError) as e:
            raise ProblemError(f"Vulcan's Hoard is not reachable at {base} ({e})",
                               ["Start Vulcan's Hoard, or upload the STL directly."])
    if data is None:
        raise ProblemError(f"model {model_id} not found in Vulcan's Hoard")
    fmt = str(info.get("format") or info.get("ext") or "").lower().lstrip(".")
    if fmt and fmt != "stl":
        raise ProblemError(f"model {model_id} is {fmt}; only STL can be imported")
    out = profile_from_stl(data, resolution_mm, thin_axis, name=str(info.get("name") or model_id))
    out["report"]["source"] = {"app": "vulcan", "model_id": model_id, "url": base, "name": info.get("name")}
    return out
