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

import hashlib
import json
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import admin, continut as modul_continut, db, motor

DIR_CONTINUT = Path(os.environ.get("PATRONACHE_CONTINUT", modul_continut.DIR_CONTINUT_IMPLICIT))
STATIC = Path(__file__).resolve().parent / "static"


class Stare:
    """Conținutul încărcat; admin-ul îl înlocuiește după o salvare reușită."""
    continut: modul_continut.Continut | None = None


def continut() -> modul_continut.Continut:
    if Stare.continut is None:
        actualizate = _seamana_continutul()
        try:
            Stare.continut = modul_continut.incarca(DIR_CONTINUT)
        except modul_continut.ContinutInvalid:
            if not actualizate:
                raise
            # Versiunea nouă din imagine nu se potrivește cu ce a editat adminul: dăm înapoi actualizarea.
            _anuleaza_actualizarea(actualizate)
            Stare.continut = modul_continut.incarca(DIR_CONTINUT)
    return Stare.continut


# Hash-uri ale versiunilor livrate înainte să existe markerul; un fișier din
# dataset identic cu una dintre ele e sigur neatins de admin și se actualizează.
HASHURI_VECHI = {
    "config.json": {
        "2ed2d2e37a7f15c8e5f5d8966efdf1e90bfc4a599e07cb06118e0480340b883e",
        "cf3b9e12bdd8409c8325c9aa2feca0cc1e8bd7f7746bfc8ae8b702d9ab300637",
    },
    "niveluri.json": {"2605c6045f062809f7aa6a4496f11099c21a18e68db5c6418a6e6f7050e56c23"},
}
MARKER = ".implicit.json"


def _hash(cale: Path) -> str:
    return hashlib.sha256(cale.read_bytes()).hexdigest()


def _citeste_marker() -> dict[str, str]:
    try:
        return json.loads((DIR_CONTINUT / MARKER).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _scrie_marker(marker: dict[str, str]) -> None:
    (DIR_CONTINUT / MARKER).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")


def _seamana_continutul() -> list[str]:
    """Ține conținutul din volumul de date în pas cu cel din imagine, fără să strice editările.

    - fișier lipsă: se copiază din imagine;
    - fișier identic cu versiunea din imagine de la ultima copiere (deci needitat din admin):
      se înlocuiește cu versiunea nouă din imagine;
    - fișier editat din admin: rămâne așa cum e.
    Întoarce numele fișierelor actualizate.
    """
    if DIR_CONTINUT == modul_continut.DIR_CONTINUT_IMPLICIT:
        return []
    DIR_CONTINUT.mkdir(parents=True, exist_ok=True)
    marker = _citeste_marker()
    actualizate: list[str] = []
    for nume in modul_continut.FISIERE:
        sursa, tinta = modul_continut.DIR_CONTINUT_IMPLICIT / nume, DIR_CONTINUT / nume
        hash_nou = _hash(sursa)
        if not tinta.exists():
            shutil.copy(sursa, tinta)
            actualizate.append(nume)
        else:
            hash_curent = _hash(tinta)
            neatins = hash_curent == marker.get(nume) or hash_curent in HASHURI_VECHI.get(nume, set())
            if neatins and hash_curent != hash_nou:
                shutil.copy(tinta, tinta.with_suffix(".json.inainte"))   # ca să putem da înapoi
                shutil.copy(sursa, tinta)
                actualizate.append(nume)
            elif not neatins and hash_curent != hash_nou:
                continue  # editat din admin, nu ne atingem și nu notăm
        marker[nume] = hash_nou
    _scrie_marker(marker)
    return actualizate


def _anuleaza_actualizarea(nume_fisiere: list[str]) -> None:
    """Pune la loc versiunile dinainte ale fișierelor actualizate automat și scoate notarea lor din marker."""
    marker = _citeste_marker()
    for nume in nume_fisiere:
        inainte = (DIR_CONTINUT / nume).with_suffix(".json.inainte")
        if inainte.exists():
            inainte.replace(DIR_CONTINUT / nume)
            marker[nume] = _hash(DIR_CONTINUT / nume)   # rămâne „neatins”, încercăm iar la versiunea următoare
    _scrie_marker(marker)


def reseteaza_fisier(nume: str) -> None:
    """Admin: aduce un fișier la versiunea din imagine și reîncarcă motorul."""
    if DIR_CONTINUT != modul_continut.DIR_CONTINUT_IMPLICIT:
        shutil.copy(modul_continut.DIR_CONTINUT_IMPLICIT / nume, DIR_CONTINUT / nume)
        marker = _citeste_marker()
        marker[nume] = _hash(DIR_CONTINUT / nume)
        _scrie_marker(marker)
    Stare.continut = modul_continut.incarca(DIR_CONTINUT)


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
    domeniu: str = Field(default="", max_length=40)


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


@app.delete("/api/partida/{id_}", status_code=204, response_class=Response)
def renunta(id_: str) -> Response:
    _partida(id_)
    db.sterge_partida(id_)
    return Response(status_code=204)


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
def pagina_joc() -> FileResponse:
    return FileResponse(STATIC / "joc.html")


@app.get("/admin", include_in_schema=False)
def pagina_admin() -> FileResponse:
    return FileResponse(STATIC / "admin.html")
