"""HTTP API and the workbench page."""
from __future__ import annotations

import pathlib
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import service

STATIC = pathlib.Path(__file__).resolve().parent / "static"
app = FastAPI(title="Maxwell's Hoard", version=service.VERSION)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class SolveIn(BaseModel):
    problem: dict[str, Any]
    refine: float = Field(1.0, gt=0, le=8)
    field: bool = True


class RefineIn(BaseModel):
    problem: dict[str, Any]
    quantities: list[str] | None = None
    levels: list[float] = [1, 2, 4]


class CompareIn(BaseModel):
    problem: dict[str, Any]
    variants: list[dict[str, Any]]
    refine: float = Field(1.0, gt=0, le=8)


class ImportIn(BaseModel):
    model_id: str | None = None
    stl_base64: str | None = None
    name: str = "uploaded STL"
    problem: dict[str, Any] | None = None
    resolution_mm: float | None = Field(None, gt=0)
    thin_axis: str | None = Field(None, pattern="^[xyz]$")
    units: str = "mm"


class SearchIn(BaseModel):
    problem: dict[str, Any]
    parameters: list[dict[str, Any]]
    objective: dict[str, Any]
    holdout: list[dict[str, Any]] | None = None
    search_refine: float = Field(1.0, gt=0, le=4)
    check_refine: float = Field(2.0, gt=0, le=8)
    finalists: int = Field(3, ge=1, le=8)
    tradeoff: str | None = None


def _ok(res):
    if isinstance(res, dict) and res.get("status") in ("invalid", "needs-input"):
        raise HTTPException(422, res)
    return res


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"service": "maxwell-hoard", "version": service.VERSION}


@app.get("/api/materials")
def materials():
    return service.materials()


@app.get("/api/examples")
def examples():
    return service.example_list()


@app.get("/api/examples/{example_id}")
def example(example_id: str):
    try:
        return service.example(example_id)
    except KeyError:
        raise HTTPException(404, "unknown example")


@app.post("/api/check")
def check(body: dict[str, Any]):
    return service.check(body.get("problem", body))


@app.post("/api/solve")
def solve(body: SolveIn):
    return _ok(service.solve(body.problem, body.refine, body.field))


@app.post("/api/refinement")
def refinement(body: RefineIn):
    return _ok(service.study_refinement(body.problem, body.quantities, body.levels))


@app.post("/api/compare")
def compare(body: CompareIn):
    return _ok(service.study_compare(body.problem, body.variants, body.refine))


@app.post("/api/search")
def search(body: SearchIn):
    return _ok(service.study_search(body.problem, body.parameters, body.objective, body.holdout,
                                    body.search_refine, body.check_refine, body.finalists, body.tradeoff))


@app.post("/api/import")
def import_geometry(body: ImportIn):
    if bool(body.model_id) == bool(body.stl_base64):
        raise HTTPException(422, {"status": "invalid", "error": "give either model_id (Vulcan) or stl_base64", "questions": []})
    if body.model_id:
        return _ok(service.import_vulcan(body.model_id, body.problem, body.resolution_mm, body.thin_axis))
    import base64
    import binascii
    try:
        data = base64.b64decode(body.stl_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, {"status": "invalid", "error": "stl_base64 is not valid base64", "questions": []})
    return _ok(service.import_stl(data, body.problem, body.resolution_mm, body.thin_axis, body.units, body.name))


@app.get("/api/references")
def references():
    return service.references()


@app.post("/api/references/{case}")
def verify(case: str, refine: float = 1.0):
    return _ok(service.verify(case, refine))


@app.get("/api/records")
def records(limit: int = 100):
    return service.records(limit)


@app.get("/api/records/{record_id}")
def record(record_id: str):
    try:
        return service.record(record_id)
    except KeyError:
        raise HTTPException(404, "unknown record")
