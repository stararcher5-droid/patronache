"""API-ul meniului de admin: citește și scrie fișierele din continut/.

O salvare validează TOT conținutul împreună (ca o legătură către o situație
ștearsă să fie prinsă), scrie fișierul și reîncarcă motorul. Partidele în curs
continuă cu conținutul nou.

Parola: dacă PATRONACHE_ADMIN_PAROLA e setată, cererile trebuie să aibă
antetul X-Parola. Fără variabilă, admin-ul e deschis (bun pentru local).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from . import continut as modul_continut

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _dir() -> Path:
    from . import main
    return main.DIR_CONTINUT


def _verifica_parola(x_parola: str | None) -> None:
    parola = os.environ.get("PATRONACHE_ADMIN_PAROLA")
    if parola and x_parola != parola:
        raise HTTPException(401, "parolă greșită")


def _fisier(nume: str) -> str:
    if nume not in modul_continut.FISIERE:
        raise HTTPException(404, f"fișier necunoscut; permise: {list(modul_continut.FISIERE)}")
    return nume


@router.get("/continut")
def citeste_tot(x_parola: str | None = Header(default=None)) -> dict[str, Any]:
    _verifica_parola(x_parola)
    d = _dir()
    return {nume: modul_continut.citeste_fisier(d, nume) for nume in modul_continut.FISIERE}


@router.get("/verifica")
def verifica(x_parola: str | None = Header(default=None)) -> dict[str, Any]:
    _verifica_parola(x_parola)
    from . import main
    c = main.continut()
    return {"avertismente": modul_continut.verifica(c), "situatii": len(c.situatii), "carti": len(c.carti)}


@router.put("/continut/{nume}")
def scrie(nume: str, corp: dict[str, Any], x_parola: str | None = Header(default=None)) -> dict[str, Any]:
    _verifica_parola(x_parola)
    nume = _fisier(nume)
    d = _dir()

    brut = {n: modul_continut.citeste_fisier(d, n) for n in modul_continut.FISIERE}
    brut[nume] = corp
    try:
        nou = modul_continut.construieste(brut)
    except modul_continut.ContinutInvalid as e:
        raise HTTPException(422, str(e))

    cale = d / nume
    temporar = cale.with_suffix(".json.tmp")
    temporar.write_text(json.dumps(corp, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporar.replace(cale)

    from . import main
    main.Stare.continut = nou
    return {"ok": True, "fisier": nume, "avertismente": modul_continut.verifica(nou)}


@router.post("/reseteaza/{nume}")
def reseteaza(nume: str, x_parola: str | None = Header(default=None)) -> dict[str, Any]:
    """Aduce fișierul la versiunea livrată cu aplicația (din imagine). Editările din el se pierd."""
    _verifica_parola(x_parola)
    nume = _fisier(nume)
    from . import main
    try:
        main.reseteaza_fisier(nume)
    except modul_continut.ContinutInvalid as e:
        raise HTTPException(422, f"versiunea implicită nu se potrivește cu restul conținutului: {e}")
    return {"ok": True, "fisier": nume, "avertismente": modul_continut.verifica(main.continut())}
