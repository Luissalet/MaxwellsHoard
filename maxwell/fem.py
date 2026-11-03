"""Quadratic-triangle finite elements for steady conduction and plane stress.

The domain is a rectangle partitioned by axis-aligned regions. Grid lines go
through every region edge, boundary-segment end and probe-free key coordinate,
so the geometry is represented exactly; each cell is split into two
six-node triangles (T6). Straight sides make the Jacobian constant, and a
degree-4 rule integrates every term exactly.
"""
from __future__ import annotations

import math
import time

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.sparse.csgraph import connected_components

from .model import LIMITS, ProblemError, resolve_material, validate

# Dunavant degree-4 rule on the reference triangle (weights sum to 1).
_A, _B = 0.445948490915965, 0.091576213509771
_WA, _WB = 0.223381589678011, 0.109951743655322
QP = np.array([[_A, _A], [1 - 2 * _A, _A], [_A, 1 - 2 * _A],
               [_B, _B], [1 - 2 * _B, _B], [_B, 1 - 2 * _B]])
QW = np.array([_WA] * 3 + [_WB] * 3)
# Natural coordinates of the six nodes (corners, then mid 1-2, 2-3, 3-1).
NODE_XI = np.array([[0, 0], [1, 0], [0, 1], [0.5, 0], [0.5, 0.5], [0, 0.5]], float)
EDGE_MASS = np.array([[4, 2, -1], [2, 16, 2], [-1, 2, 4]]) / 30.0  # nodes end, mid, end
EDGE_LOAD = np.array([1, 4, 1]) / 6.0


def shape(xi, eta):
    l1, l2, l3 = 1 - xi - eta, xi, eta
    return np.array([l1 * (2 * l1 - 1), l2 * (2 * l2 - 1), l3 * (2 * l3 - 1),
                     4 * l1 * l2, 4 * l2 * l3, 4 * l3 * l1])


def dshape(xi, eta):
    l1, l2, l3 = 1 - xi - eta, xi, eta
    dxi = [-(4 * l1 - 1), 4 * l2 - 1, 0.0, 4 * (l1 - l2), 4 * l3, -4 * l3]
    deta = [-(4 * l1 - 1), 0.0, 4 * l3 - 1, -4 * l2, 4 * l2, 4 * (l1 - l3)]
    return np.array([dxi, deta])


def _lines(length, keys, size):
    pts = sorted({0.0, length, *[k for k in keys if 0.0 < k < length]})
    merged = [pts[0]]
    tol = length * 1e-9
    for v in pts[1:]:
        if v - merged[-1] > tol:
            merged.append(v)
    merged[-1] = length
    out = [merged[0]]
    for a, b in zip(merged, merged[1:]):
        n = max(1, math.ceil((b - a) / size - 1e-9))
        out.extend(a + (b - a) * np.arange(1, n + 1) / n)
    return np.array(out)


class Mesh:
    def __init__(self, p: dict, refine: float = 1.0):
        W, H = p["domain"]["width"], p["domain"]["height"]
        size = p["mesh"]["size"] / refine
        xk, yk = [], []
        for r in p["regions"]:
            xk += [r["x0"], r["x1"]]
            yk += [r["y0"], r["y1"]]
        for b in p["boundary"]:
            (yk if b["edge"] in ("left", "right") else xk).extend([b["from"], b["to"]])
        self.xs, self.ys = _lines(W, xk, size), _lines(H, yk, size)
        nx, ny = len(self.xs) - 1, len(self.ys) - 1
        if nx * ny > LIMITS["max_cells"]:
            raise ProblemError(f"mesh too fine: {nx * ny} cells, limit {LIMITS['max_cells']}")
        xr = np.empty(2 * nx + 1)
        xr[0::2], xr[1::2] = self.xs, (self.xs[:-1] + self.xs[1:]) / 2
        yr = np.empty(2 * ny + 1)
        yr[0::2], yr[1::2] = self.ys, (self.ys[:-1] + self.ys[1:]) / 2
        NX = 2 * nx + 1
        gid = lambda I, J: J * NX + I
        cx = (self.xs[:-1] + self.xs[1:]) / 2
        cy = (self.ys[:-1] + self.ys[1:]) / 2
        CX, CY = np.meshgrid(cx, cy, indexing="xy")  # shape (ny, nx)
        mat = np.full(CX.shape, p["material"], dtype=object)
        void = np.zeros(CX.shape, bool)
        self.region_mask = {}
        for r in p["regions"]:
            m = (CX > r["x0"]) & (CX < r["x1"]) & (CY > r["y0"]) & (CY < r["y1"])
            self.region_mask[r["id"]] = m
            if r["void"]:
                void |= m
            elif r.get("material"):
                mat[m] = r["material"]
                void[m] = False
        elems, ecell = [], []
        for j in range(ny):
            for i in range(nx):
                if void[j, i]:
                    continue
                I, J = 2 * i, 2 * j
                A, B, C, D = gid(I, J), gid(I + 2, J), gid(I + 2, J + 2), gid(I, J + 2)
                E = gid(I + 1, J + 1)
                elems.append([A, B, C, gid(I + 1, J), gid(I + 2, J + 1), E])
                elems.append([A, C, D, E, gid(I + 1, J + 2), gid(I, J + 1)])
                ecell += [(j, i), (j, i)]
        if not elems:
            raise ProblemError("the whole domain is void")
        elems = np.array(elems)
        used = np.unique(elems)
        remap = -np.ones((2 * ny + 1) * NX, int)
        remap[used] = np.arange(len(used))
        self.elems = remap[elems]
        XR, YR = np.meshgrid(xr, yr, indexing="xy")
        self.nodes = np.column_stack([XR.ravel()[used], YR.ravel()[used]])
        self.corner = np.zeros(len(used), bool)
        self.corner[np.unique(self.elems[:, :3])] = True
        self.cells = np.array(ecell)
        self.void = void
        self.mat = np.array([mat[j, i] for j, i in ecell], dtype=object)
        self.nx, self.ny = nx, ny
        self._remap, self._NX = remap, NX
        # Jacobian of each element (constant on straight-sided triangles).
        xy = self.nodes[self.elems[:, :3]]
        J = np.stack([xy[:, 1] - xy[:, 0], xy[:, 2] - xy[:, 0]], axis=1)  # (ne, 2, 2) rows xi, eta
        self.detJ = J[:, 0, 0] * J[:, 1, 1] - J[:, 0, 1] * J[:, 1, 0]
        self.J = J
        self.invJ = np.linalg.inv(J)
        self.area = self.detJ / 2

    def grads(self, xi, eta):
        """dN/dx, dN/dy for every element at one natural point: (ne, 2, 6)."""
        return np.einsum("eij,jk->eik", self.invJ, dshape(xi, eta))

    def boundary_edges(self, edge, a, b):
        """Element edges on an outer side within [a, b]: list of (n_end, n_mid, n_end, length)."""
        out = []
        if edge in ("left", "right"):
            i = 0 if edge == "left" else self.nx - 1
            I = 0 if edge == "left" else 2 * self.nx
            for j in range(self.ny):
                if self.void[j, i] or self.ys[j] < a - 1e-12 or self.ys[j + 1] > b + 1e-12:
                    continue
                ids = [self._remap[(2 * j + k) * self._NX + I] for k in range(3)]
                out.append((ids, self.ys[j + 1] - self.ys[j]))
        else:
            j = 0 if edge == "bottom" else self.ny - 1
            J = 0 if edge == "bottom" else 2 * self.ny
            for i in range(self.nx):
                if self.void[j, i] or self.xs[i] < a - 1e-12 or self.xs[i + 1] > b + 1e-12:
                    continue
                ids = [self._remap[J * self._NX + 2 * i + k] for k in range(3)]
                out.append((ids, self.xs[i + 1] - self.xs[i]))
        return out

    def locate(self, x, y):
        """Element index and natural coordinates containing (x, y), or None."""
        xy = self.nodes[self.elems[:, :3]]
        d = np.array([x, y]) - xy[:, 0]
        # natural coords: [x - x1] = J^T [xi, eta]
        Jt = np.transpose(self.J, (0, 2, 1))
        nat = np.linalg.solve(Jt, d[..., None])[..., 0]
        ok = (nat[:, 0] >= -1e-9) & (nat[:, 1] >= -1e-9) & (nat.sum(1) <= 1 + 1e-9)
        idx = np.flatnonzero(ok)
        if not len(idx):
            return None
        return int(idx[0]), nat[idx[0]]


def _pieces(mesh):
    """Pieces of the body: elements joined through a shared edge (a shared
    mid-side node). Pieces that touch only at a corner are separate, because
    a single node cannot carry a moment or a meaningful heat flow."""
    ne = len(mesh.elems)
    rows = np.repeat(np.arange(ne), 3)
    inc = sp.csr_matrix((np.ones(ne * 3), (rows, mesh.elems[:, 3:].ravel())), shape=(ne, len(mesh.nodes)))
    n, labels = connected_components(inc @ inc.T, directed=False)
    return n, labels


def _pieces_touching(mesh, labels, nodes):
    """Pieces that own at least one of the given nodes."""
    if len(nodes) == 0:
        return set()
    hit = np.isin(mesh.elems, np.asarray(nodes)).any(1)
    return set(labels[hit].tolist())


def _material_arrays(p, mesh, key):
    cache = {}
    vals = []
    for m in mesh.mat:
        if m not in cache:
            cache[m] = resolve_material(p, m)
        vals.append(cache[m].get(key))
    return np.array(vals, float)


def _assemble(mesh, ke, dofs_per_node):
    ne = len(mesh.elems)
    nd = 6 * dofs_per_node
    if dofs_per_node == 1:
        edofs = mesh.elems
    else:
        edofs = np.empty((ne, 12), int)
        edofs[:, 0::2] = 2 * mesh.elems
        edofs[:, 1::2] = 2 * mesh.elems + 1
    rows = np.repeat(edofs, nd, axis=1).ravel()
    cols = np.tile(edofs, (1, nd)).ravel()
    n = len(mesh.nodes) * dofs_per_node
    return sp.csr_matrix((ke.ravel(), (rows, cols)), shape=(n, n)), edofs


def _mass_like(mesh, coef):
    """coef_e * integral(N N^T) per element: (ne, 6, 6)."""
    M = sum(w * np.outer(shape(*q), shape(*q)) for q, w in zip(QP, QW))
    return (coef * mesh.area)[:, None, None] * M[None]


def _load_like(mesh, coef):
    vec = sum(w * shape(*q) for q, w in zip(QP, QW))
    return (coef * mesh.area)[:, None] * vec[None]


def _scatter(n, idx, vals):
    out = np.zeros(n)
    np.add.at(out, idx.ravel(), vals.ravel())
    return out


def _solve(K, f, fixed, values):
    n = K.shape[0]
    free = np.setdiff1d(np.arange(n), fixed)
    u = np.zeros(n)
    u[fixed] = values
    rhs = f[free] - K[free][:, fixed] @ u[fixed]
    Kff = K[free][:, free].tocsc()
    u[free] = spla.spsolve(Kff, rhs)
    if not np.all(np.isfinite(u)):
        raise ProblemError("the linear system is singular", ["Is every piece of the part held or cooled somewhere?"])
    return u


def solve_thermal(p, mesh):
    t = p["thickness"]
    k = _material_arrays(p, mesh, "k")
    n = len(mesh.nodes)
    ke = np.zeros((len(mesh.elems), 6, 6))
    for q, w in zip(QP, QW):
        G = mesh.grads(*q)
        ke += (w * mesh.detJ / 2 * k * t)[:, None, None] * np.einsum("eij,eik->ejk", G, G)
    face_h = np.zeros(len(mesh.elems))
    face_ht = np.zeros(len(mesh.elems))
    source = np.zeros(len(mesh.elems))
    elem_region = {}
    if p.get("face_convection"):
        fc = p["face_convection"]
        face_h[:] = fc["h"] * fc["sides"]
        face_ht[:] = fc["h"] * fc["sides"] * fc["t_inf"]
    for r in p["regions"]:
        m = mesh.region_mask[r["id"]][mesh.cells[:, 0], mesh.cells[:, 1]]
        elem_region[r["id"]] = m
        if r["void"]:
            continue
        if "face_convection" in r:
            fc = r["face_convection"]
            face_h[m] = fc["h"] * fc["sides"]
            face_ht[m] = fc["h"] * fc["sides"] * fc["t_inf"]
        if "q" in r:
            source[m] += r["q"]
        if "power" in r:
            vol = mesh.area[m].sum() * t
            if vol <= 0:
                raise ProblemError(f"region {r['id']} has power but no material")
            source[m] += r["power"] / vol
    ke += _mass_like(mesh, face_h)
    K, _ = _assemble(mesh, ke, 1)
    f = _scatter(n, mesh.elems, _load_like(mesh, source * t + face_ht))
    fixed, vals = [], []
    edge_conv = []
    for b in p["boundary"]:
        edges = mesh.boundary_edges(b["edge"], b["from"], b["to"])
        if b["type"] != "insulated" and not edges:
            raise ProblemError(f"condition '{b['label']}' falls on a void part of the {b['edge']} edge")
        for ids, L in edges:
            ids = np.array(ids)
            if b["type"] == "temperature":
                fixed += list(ids)
                vals += [b["value"]] * 3
            elif b["type"] == "convection":
                K = K + sp.csr_matrix((b["h"] * t * L * EDGE_MASS.ravel(), (np.repeat(ids, 3), np.tile(ids, 3))), shape=K.shape)
                f[ids] += b["h"] * t * b["t_inf"] * L * EDGE_LOAD
                edge_conv.append((ids, L, b))
            elif b["type"] == "flux":
                f[ids] += b["q"] * t * L * EDGE_LOAD
    fixed = np.array(fixed, int)
    vals = np.array(vals, float)
    if len(fixed):
        fixed, first = np.unique(fixed, return_index=True)
        vals = vals[first]
    ncomp, labels = _pieces(mesh)
    cooled = _pieces_touching(mesh, labels, fixed)
    for ids, _, _ in edge_conv:
        cooled |= _pieces_touching(mesh, labels, ids)
    cooled |= set(labels[face_h > 0].tolist())
    if len(cooled) < ncomp:
        raise ProblemError("part of the body has no fixed temperature and no convection: its temperature is undetermined",
                           ["Where does the heat leave the part? Give a fixed temperature, an edge convection or a face convection for every separate piece."])
    T = _solve(K.tocsr(), f, fixed, vals)
    # Energy balance: sources + flux in = convection out + heat through fixed-temperature edges.
    q_src = float((source * mesh.area * t).sum())
    q_flux = sum(b["q"] * t * L for b in p["boundary"] if b["type"] == "flux"
                 for _, L in mesh.boundary_edges(b["edge"], b["from"], b["to"]))
    q_edge_conv = sum(float(b["h"] * t * L * (EDGE_LOAD @ T[ids] - b["t_inf"])) for ids, L, b in edge_conv)
    Tq = sum(w * (T[mesh.elems] @ shape(*q)) for q, w in zip(QP, QW))
    q_face = float(((face_h * Tq - face_ht) * mesh.area).sum())
    q_fixed = 0.0
    if len(fixed):
        Kc = K.tocsr()
        r = Kc[fixed] @ T - f[fixed]
        q_fixed = float(-r.sum())  # K T - f is the heat injected at fixed nodes; its negative leaves there
    inflow = q_src + q_flux
    outflow = q_edge_conv + q_face + q_fixed
    throughput = abs(q_src) + abs(q_flux) + abs(q_edge_conv) + abs(q_face) + abs(q_fixed)
    if throughput > 0 and abs(inflow - outflow) / throughput > 1e-6:
        raise ProblemError("the solution does not balance the heat flows: the model is ill-conditioned")
    region_avg = {}
    for rid, m in elem_region.items():
        if m.any() and not next(r for r in p["regions"] if r["id"] == rid)["void"]:
            region_avg[rid] = float((Tq[m] * mesh.area[m]).sum() / mesh.area[m].sum())
    imax, imin = int(np.argmax(T)), int(np.argmin(T))
    summary = {
        "max_temperature": float(T[imax]), "max_at": mesh.nodes[imax].tolist(),
        "min_temperature": float(T[imin]), "min_at": mesh.nodes[imin].tolist(),
        "region_avg_temperature": region_avg,
        "heat_balance": {"sources_W": q_src, "flux_in_W": q_flux, "edge_convection_out_W": q_edge_conv,
                         "face_convection_out_W": q_face, "fixed_temperature_out_W": q_fixed,
                         "relative_residual": abs(inflow - outflow) / max(throughput, 1e-30)},
    }
    return {"T": T, "summary": summary}


def _D(E, nu):
    c = E / (1 - nu ** 2)
    return np.stack([np.stack([c, c * nu, 0 * c], -1), np.stack([c * nu, c, 0 * c], -1),
                     np.stack([0 * c, 0 * c, c * (1 - nu) / 2], -1)], -2)


def _B(G):
    ne = G.shape[0]
    B = np.zeros((ne, 3, 12))
    B[:, 0, 0::2] = G[:, 0]
    B[:, 1, 1::2] = G[:, 1]
    B[:, 2, 0::2] = G[:, 1]
    B[:, 2, 1::2] = G[:, 0]
    return B


def solve_elastic(p, mesh):
    t = p["thickness"]
    E, nu = _material_arrays(p, mesh, "E"), _material_arrays(p, mesh, "nu")
    rho = _material_arrays(p, mesh, "density")
    D = _D(E, nu)
    ke = np.zeros((len(mesh.elems), 12, 12))
    for q, w in zip(QP, QW):
        B = _B(mesh.grads(*q))
        ke += (w * mesh.detJ / 2 * t)[:, None, None] * np.einsum("eki,ekl,elj->eij", B, D, B)
    K, edofs = _assemble(mesh, ke, 2)
    n = 2 * len(mesh.nodes)
    f = np.zeros(n)
    g = p.get("gravity", 0.0)
    if g:
        if np.isnan(rho).any():
            raise ProblemError("gravity needs the density of every material", ["What is the density of each material?"])
        fy = _load_like(mesh, -rho * g * t)
        np.add.at(f, 2 * mesh.elems.ravel() + 1, fy.ravel())
    fixed = []
    applied = np.zeros(2)
    for b in p["boundary"]:
        edges = mesh.boundary_edges(b["edge"], b["from"], b["to"])
        if b["type"] in ("force", "pressure") and not edges:
            raise ProblemError(f"load '{b['label']}' falls on a void part of the {b['edge']} edge")
        total_len = sum(L for _, L in edges)
        normal = {"left": (-1, 0), "right": (1, 0), "bottom": (0, -1), "top": (0, 1)}[b["edge"]]
        for ids, L in edges:
            ids = np.array(ids)
            if b["type"] == "fixed":
                if "x" in b["dofs"]:
                    fixed += list(2 * ids)
                if "y" in b["dofs"]:
                    fixed += list(2 * ids + 1)
            elif b["type"] == "force":
                f[2 * ids] += b["fx"] / total_len * L * EDGE_LOAD
                f[2 * ids + 1] += b["fy"] / total_len * L * EDGE_LOAD
            elif b["type"] == "pressure":
                tr = -b["p"] * t
                f[2 * ids] += tr * normal[0] * L * EDGE_LOAD
                f[2 * ids + 1] += tr * normal[1] * L * EDGE_LOAD
    fixed = np.unique(np.array(fixed, int))
    applied = np.array([f[0::2].sum(), f[1::2].sum()])
    # Every connected piece must be held against translation and rotation.
    ncomp, labels = _pieces(mesh)
    for c in range(ncomp):
        nodes_c = np.unique(mesh.elems[labels == c])
        X = mesh.nodes[nodes_c]
        xc = X.mean(0)
        R = np.zeros((n, 3))
        R[2 * nodes_c, 0] = 1
        R[2 * nodes_c + 1, 1] = 1
        R[2 * nodes_c, 2] = -(X[:, 1] - xc[1])
        R[2 * nodes_c + 1, 2] = X[:, 0] - xc[0]
        rank = np.linalg.matrix_rank(R[fixed], tol=1e-9 * max(p["domain"]["width"], p["domain"]["height"])) if len(fixed) else 0
        if rank < 3:
            raise ProblemError("the part (or a separate piece of it) can move as a rigid body: supports are missing",
                               ["How is the part actually held? Say which edges are clamped or which directions are blocked, for every separate piece."])
    u = _solve(K.tocsr(), f, fixed, np.zeros(len(fixed)))
    reactions = K.tocsr()[fixed] @ u - f[fixed]
    rx = reactions[fixed % 2 == 0].sum()
    ry = reactions[fixed % 2 == 1].sum()
    residual = float(np.hypot(applied[0] + rx, applied[1] + ry) / max(np.hypot(*applied), 1e-30))
    if np.hypot(*applied) > 0 and residual > 1e-6:
        raise ProblemError(f"the solution does not balance the loads (residual {residual:.2e}): the model is ill-conditioned",
                           ["Check that every piece is held by a real edge, not by a single point."])
    # Stresses at the six nodes of each element (linear inside a T6).
    ue = u[edofs]
    vm_nodes = np.zeros((len(mesh.elems), 6))
    sig_nodes = np.zeros((len(mesh.elems), 6, 3))
    for a, (xi, eta) in enumerate(NODE_XI):
        B = _B(mesh.grads(xi, eta))
        s = np.einsum("eij,ejk,ek->ei", D, B, ue)
        sig_nodes[:, a] = s
        vm_nodes[:, a] = np.sqrt(s[:, 0] ** 2 - s[:, 0] * s[:, 1] + s[:, 1] ** 2 + 3 * s[:, 2] ** 2)
    vm_avg = np.zeros(len(mesh.nodes))
    cnt = np.zeros(len(mesh.nodes))
    np.add.at(vm_avg, mesh.elems.ravel(), vm_nodes.ravel())
    np.add.at(cnt, mesh.elems.ravel(), 1)
    vm_avg /= np.maximum(cnt, 1)
    ux, uy = u[0::2], u[1::2]
    mag = np.hypot(ux, uy)
    imax = int(np.argmax(mag))
    ivm = int(np.argmax(vm_avg))
    mass = float((rho * mesh.area * t).sum()) if not np.isnan(rho).any() else None
    yields = _material_arrays(p, mesh, "yield")
    sf = None
    if not np.isnan(yields).all():
        ratio = vm_nodes.max(1) / np.where(np.isnan(yields), np.inf, yields)
        worst = ratio.max()
        sf = float(1 / worst) if worst > 0 else None
    summary = {
        "max_displacement": float(mag[imax]), "max_displacement_at": mesh.nodes[imax].tolist(),
        "max_abs_ux": float(np.abs(ux).max()), "max_abs_uy": float(np.abs(uy).max()),
        "max_von_mises": float(vm_avg[ivm]), "max_von_mises_at": mesh.nodes[ivm].tolist(),
        "max_von_mises_unaveraged": float(vm_nodes.max()),
        "mass": mass, "safety_factor": sf,
        "equilibrium": {"applied_fx": float(applied[0]), "applied_fy": float(applied[1]),
                        "reaction_fx": float(rx), "reaction_fy": float(ry),
                        "relative_residual": residual},
        "compliance_J": float(f @ u),
    }
    return {"u": u, "vm": vm_avg, "vm_nodes": vm_nodes, "sig_nodes": sig_nodes, "summary": summary}


def _probe(p, mesh, sol, probe):
    loc = mesh.locate(probe["x"], probe["y"])
    out = {"id": probe["id"], "x": probe["x"], "y": probe["y"]}
    if loc is None:
        out["error"] = "point is outside the material"
        return out
    e, (xi, eta) = loc
    N = shape(xi, eta)
    ids = mesh.elems[e]
    if p["physics"] == "thermal":
        out["temperature"] = float(N @ sol["T"][ids])
    else:
        u = sol["u"]
        out["ux"], out["uy"] = float(N @ u[2 * ids]), float(N @ u[2 * ids + 1])
        out["displacement"] = math.hypot(out["ux"], out["uy"])
        s = N @ sol["sig_nodes"][e]
        out["sxx"], out["syy"], out["sxy"] = map(float, s)
        out["von_mises"] = float(math.sqrt(s[0] ** 2 - s[0] * s[1] + s[1] ** 2 + 3 * s[2] ** 2))
    return out


def quantity(result: dict, name: str):
    s = result["summary"]
    if ":" in name:
        kind, key = name.split(":", 1)
        if kind == "region_avg_temperature":
            return s.get("region_avg_temperature", {}).get(key)
        probe = next((pr for pr in result.get("probes", []) if pr["id"] == key), None)
        if probe is None:
            return None
        return probe.get({"probe_temperature": "temperature", "probe_displacement": "displacement",
                          "probe_von_mises": "von_mises"}[kind])
    return s.get(name)


def check_requirements(p, result):
    out = []
    for rq in p["requirements"]:
        v = quantity(result, rq["quantity"])
        ok = v is not None and ("max" not in rq or v <= rq["max"]) and ("min" not in rq or v >= rq["min"])
        out.append({**rq, "value": v, "ok": bool(ok)})
    return out


def assumptions(p, mesh):
    mats = sorted(set(mesh.mat))
    notes = [f"Two-dimensional model of the {p['domain']['width']} m x {p['domain']['height']} m profile with uniform thickness {p['thickness']} m."]
    if p["physics"] == "thermal":
        notes.append("Steady-state conduction; properties independent of temperature; no radiation unless included in a convection coefficient.")
        notes.append("Edges with no condition are insulated; heat sources are spread uniformly over their region.")
    else:
        notes.append("Linear elasticity, plane stress, small displacements; no contact, buckling or plasticity checked.")
        notes.append("Edges with no condition are free; forces are spread uniformly along their segment.")
        notes.append("Stresses at re-entrant corners and at the ends of clamped edges are singular: their value grows with refinement. Use the refinement study before trusting a peak.")
    for m in mats:
        mat = resolve_material(p, m)
        keys = ("k",) if p["physics"] == "thermal" else ("E", "nu", "density", "yield")
        vals = ", ".join(f"{k}={mat.get(k)}" for k in keys)
        notes.append(f"Material {m} ({mat.get('label', m)}): {vals} — nominal values, confirm with the supplier datasheet.")
    return notes


def run(problem: dict, refine: float = 1.0, field: bool = True) -> dict:
    t0 = time.perf_counter()
    if not 0 < float(refine) <= 8:
        raise ProblemError("refine must be between 0 and 8")
    p = validate(problem)
    mesh = Mesh(p, refine)
    dpn = 1 if p["physics"] == "thermal" else 2
    if len(mesh.nodes) * dpn > LIMITS["max_dofs"]:
        raise ProblemError(f"mesh too fine: {len(mesh.nodes) * dpn} unknowns, limit {LIMITS['max_dofs']}")
    sol = solve_thermal(p, mesh) if p["physics"] == "thermal" else solve_elastic(p, mesh)
    result = {
        "status": "solved", "physics": p["physics"], "name": p["name"],
        "summary": sol["summary"],
        "mesh": {"cells": int(mesh.nx * mesh.ny - mesh.void.sum()), "elements": int(len(mesh.elems)),
                 "nodes": int(len(mesh.nodes)), "unknowns": int(len(mesh.nodes) * dpn), "element": "T6 (quadratic triangle)",
                 "size": p["mesh"]["size"] / refine, "refine": refine},
        "assumptions": assumptions(p, mesh),
    }
    result["probes"] = [_probe(p, mesh, sol, pr) for pr in p["probes"]]
    result["requirements"] = check_requirements(p, result)
    result["verdict"] = ("pass" if all(r["ok"] for r in result["requirements"]) else "fail") if result["requirements"] else "no-requirements"
    if field and len(mesh.elems) <= 30_000:
        result["field"] = _field(p, mesh, sol)
    result["seconds"] = round(time.perf_counter() - t0, 3)
    return result


def _field(p, mesh, sol):
    """Linear sub-triangles over all six nodes, for drawing."""
    e = mesh.elems
    tris = np.concatenate([e[:, [0, 3, 5]], e[:, [3, 1, 4]], e[:, [5, 4, 2]], e[:, [3, 4, 5]]])
    out = {"x": np.round(mesh.nodes[:, 0], 9).tolist(), "y": np.round(mesh.nodes[:, 1], 9).tolist(),
           "triangles": tris.tolist(), "voids": [], "width": p["domain"]["width"], "height": p["domain"]["height"]}
    if p["physics"] == "thermal":
        out["values"] = {"temperature": np.round(sol["T"], 6).tolist()}
    else:
        u = sol["u"]
        out["values"] = {"displacement": np.round(np.hypot(u[0::2], u[1::2]), 12).tolist(),
                         "von_mises": np.round(sol["vm"], 3).tolist()}
        out["ux"] = np.round(u[0::2], 12).tolist()
        out["uy"] = np.round(u[1::2], 12).tolist()
    out["regions"] = [{k: r[k] for k in ("id", "x0", "y0", "x1", "y1", "void")} for r in p["regions"]]
    return out
