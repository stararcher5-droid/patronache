"""API-ul jocului Patronache.

Joc:
    POST   /api/partida                 pornește o partidă -> {id, pas}
    GET    /api/partida/{id}            pasul curent
    POST   /api/partida/{id}/alege      {"optiune": 0..3} -> efect + pasul următor
    POST   /api/partida/{id}/carte      {"carte": "<id>"} folosește o carte din inventar
    POST   /api/partida/{id}/bilant     închide anul -> profit, nivel + pasul următor
    GET    /api/partida/{id}/rezultat   rezultatul final (doar după final)
    DELETE /api/partida/{id}            renunță la partidă
    GET    /api/continut                reguli, niveluri, cărți, arhetipuri (fără efecte ascunse)
    GET    /api/statistici              numere anonime
    GET    /sanatate

Admin (meniul de editat conținutul, la /admin; vezi admin.py):
    GET    /api/admin/continut
    PUT    /api/admin/continut/{fisier}
    GET    /api/admin/verifica
"""
from __future__ import annotations

import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import admin, continut as modul_continut, db, motor

DIR_CONTINUT = Path(os.environ.get("PATRONACHE_CONTINUT", modul_continut.DIR_CONTINUT_IMPLICIT))
STATIC = Path(__file__).resolve().parent / "static"


class Stare:
    """Conținutul încărcat; admin-ul îl înlocuiește după o salvare reușită."""
    continut: modul_continut.Continut | None = None


def continut() -> modul_continut.Continut:
    if Stare.continut is None:
        _seamana_continutul()
        Stare.continut = modul_continut.incarca(DIR_CONTINUT)
    return Stare.continut


def _seamana_continutul() -> None:
    """Pe un volum gol (prima pornire în Docker) copiază conținutul din imagine, ca admin-ul să aibă ce edita."""
    if DIR_CONTINUT == modul_continut.DIR_CONTINUT_IMPLICIT or (DIR_CONTINUT / "config.json").exists():
        return
    DIR_CONTINUT.mkdir(parents=True, exist_ok=True)
    for nume in modul_continut.FISIERE:
        if not (DIR_CONTINUT / nume).exists():
            shutil.copy(modul_continut.DIR_CONTINUT_IMPLICIT / nume, DIR_CONTINUT / nume)


@asynccontextmanager
async def durata(app: FastAPI):
    continut()
    db.conexiune()
    yield
    db.inchide()


app = FastAPI(title="Patronache", version="0.2.0", lifespan=durata)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(admin.router)


# ---------------------------------------------------------------- modele

class FirmaNoua(BaseModel):
    nume: str = Field(default="Patronache SRL", max_length=40)
    slogan: str = Field(default="", max_length=80)
    culoare: str = Field(default="", max_length=20)
    sigla: str = Field(default="", max_length=8)


class Alegere(BaseModel):
    optiune: int = Field(ge=0, le=3)


class Carte(BaseModel):
    carte: str = Field(max_length=80)


# ---------------------------------------------------------------- ajutoare

def _partida(id_: str) -> dict[str, Any]:
    stare = db.citeste_partida(id_)
    if stare is None:
        raise HTTPException(404, "partida nu există")
    return stare


def _raspuns(id_: str, stare: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    r = {"id": id_, "pas": motor.pas_curent(continut(), stare)}
    if extra:
        r.update(extra)
    return r


def _noteaza_final(c: modul_continut.Continut, stare: dict[str, Any]) -> None:
    f = stare.get("final")
    if not f or f.get("notat"):
        return
    arhetip = None
    if f["mandat_complet"]:
        castigator = motor.potrivire(c, stare)["castigator"]
        arhetip = castigator["id"] if castigator else None
    db.noteaza_final(f["motiv"], arhetip, stare["nivel"])
    f["notat"] = True


# ---------------------------------------------------------------- rute joc

@app.get("/sanatate")
def sanatate() -> dict[str, Any]:
    c = continut()
    return {"ok": True, "situatii": len(c.situatii), "avertismente": len(modul_continut.verifica(c))}


@app.get("/api/continut")
def continut_public() -> dict[str, Any]:
    return continut().public()


@app.get("/api/statistici")
def statistici() -> dict[str, Any]:
    return db.statistici()


@app.post("/api/partida", status_code=201)
def partida_noua(firma: FirmaNoua) -> dict[str, Any]:
    try:
        stare = motor.stare_noua(continut(), firma.model_dump())
    except motor.ActiuneInvalida as e:
        raise HTTPException(503, str(e))
    return _raspuns(db.creeaza_partida(stare), stare)


@app.get("/api/partida/{id_}")
def partida(id_: str) -> dict[str, Any]:
    return _raspuns(id_, _partida(id_))


@app.delete("/api/partida/{id_}", status_code=204)
def renunta(id_: str) -> None:
    _partida(id_)
    db.sterge_partida(id_)


@app.post("/api/partida/{id_}/alege")
def alege(id_: str, alegere: Alegere) -> dict[str, Any]:
    stare = _partida(id_)
    c = continut()
    pas_id = stare["pas_id"]
    try:
        efect = motor.alege(c, stare, alegere.optiune)
    except motor.ActiuneInvalida as e:
        raise HTTPException(409, str(e))
    except KeyError:
        # Situația curentă a fost ștearsă din admin în timpul partidei.
        raise HTTPException(409, "situația curentă nu mai există în conținut; pornește o partidă nouă")
    _noteaza_final(c, stare)
    db.salveaza_partida(id_, stare)
    db.noteaza_alegere(pas_id, alegere.optiune)
    efect["procente"] = db.procente_alegeri(pas_id, len(c.situatie(pas_id)["optiuni"]))
    return _raspuns(id_, stare, {"efect": efect})


@app.post("/api/partida/{id_}/carte")
def foloseste_carte(id_: str, corp: Carte) -> dict[str, Any]:
    stare = _partida(id_)
    c = continut()
    try:
        efect = motor.foloseste_carte(c, stare, corp.carte)
    except motor.ActiuneInvalida as e:
        raise HTTPException(409, str(e))
    _noteaza_final(c, stare)
    db.salveaza_partida(id_, stare)
    return _raspuns(id_, stare, {"efect": efect})


@app.post("/api/partida/{id_}/bilant")
def bilant(id_: str) -> dict[str, Any]:
    stare = _partida(id_)
    c = continut()
    try:
        rezultat = motor.bilant(c, stare)
    except motor.ActiuneInvalida as e:
        raise HTTPException(409, str(e))
    _noteaza_final(c, stare)
    db.salveaza_partida(id_, stare)
    return _raspuns(id_, stare, {"bilant": rezultat})


@app.get("/api/partida/{id_}/rezultat")
def rezultat(id_: str) -> dict[str, Any]:
    stare = _partida(id_)
    try:
        return motor.rezultat(continut(), stare)
    except motor.ActiuneInvalida as e:
        raise HTTPException(409, str(e))


# ---------------------------------------------------------------- meniul de admin (pagina)

@app.get("/", include_in_schema=False)
def radacina() -> RedirectResponse:
    # Până apare interfața jocului, rădăcina duce la meniul de admin.
    return RedirectResponse("/admin")


@app.get("/admin", include_in_schema=False)
def pagina_admin() -> FileResponse:
    return FileResponse(STATIC / "admin.html")
