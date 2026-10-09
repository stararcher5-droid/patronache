"""SQLite: partidele în curs și statistici anonime despre alegeri.

Nu păstrăm nimic despre jucător: doar starea partidei (sub un cod aleator) și,
separat, câți au ales fiecare opțiune la fiecare situație și cum s-au terminat partidele.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from pathlib import Path
from typing import Any

CALE_DB = Path(os.environ.get("PATRONACHE_DB", Path(__file__).resolve().parent.parent / "data" / "patronache.db"))

_lacat = threading.Lock()
_con: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS partide (
    id         TEXT PRIMARY KEY,
    stare      TEXT NOT NULL,
    creat      TEXT NOT NULL DEFAULT (datetime('now')),
    actualizat TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS alegeri (
    situatie  TEXT NOT NULL,
    optiune   INTEGER NOT NULL,
    numar     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (situatie, optiune)
);
CREATE TABLE IF NOT EXISTS finaluri (
    motiv     TEXT NOT NULL,
    arhetip   TEXT NOT NULL DEFAULT '',
    nivel     INTEGER NOT NULL DEFAULT 1,
    numar     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (motiv, arhetip, nivel)
);
"""


def conexiune() -> sqlite3.Connection:
    global _con
    if _con is None:
        CALE_DB.parent.mkdir(parents=True, exist_ok=True)
        _con = sqlite3.connect(CALE_DB, check_same_thread=False)
        _con.row_factory = sqlite3.Row
        _con.execute("PRAGMA journal_mode=WAL")
        _con.executescript(SCHEMA)
    return _con


def inchide() -> None:
    global _con
    if _con is not None:
        _con.close()
        _con = None


# ---------------------------------------------------------------- partide

def creeaza_partida(stare: dict[str, Any]) -> str:
    id_ = secrets.token_urlsafe(12)
    with _lacat:
        conexiune().execute("INSERT INTO partide (id, stare) VALUES (?, ?)", (id_, json.dumps(stare, ensure_ascii=False)))
        conexiune().commit()
    return id_


def citeste_partida(id_: str) -> dict[str, Any] | None:
    rand = conexiune().execute("SELECT stare FROM partide WHERE id = ?", (id_,)).fetchone()
    return json.loads(rand["stare"]) if rand else None


def salveaza_partida(id_: str, stare: dict[str, Any]) -> None:
    with _lacat:
        conexiune().execute(
            "UPDATE partide SET stare = ?, actualizat = datetime('now') WHERE id = ?",
            (json.dumps(stare, ensure_ascii=False), id_),
        )
        conexiune().commit()


def sterge_partida(id_: str) -> None:
    with _lacat:
        conexiune().execute("DELETE FROM partide WHERE id = ?", (id_,))
        conexiune().commit()


# ---------------------------------------------------------------- statistici

def noteaza_alegere(situatie: str, optiune: int) -> None:
    with _lacat:
        conexiune().execute(
            "INSERT INTO alegeri (situatie, optiune, numar) VALUES (?, ?, 1) "
            "ON CONFLICT(situatie, optiune) DO UPDATE SET numar = numar + 1",
            (situatie, optiune),
        )
        conexiune().commit()


def procente_alegeri(situatie: str, nr_optiuni: int) -> list[int]:
    """Cât la sută dintre jucători au ales fiecare opțiune."""
    randuri = conexiune().execute("SELECT optiune, numar FROM alegeri WHERE situatie = ?", (situatie,)).fetchall()
    numere = [0] * nr_optiuni
    for r in randuri:
        if 0 <= r["optiune"] < nr_optiuni:
            numere[r["optiune"]] = r["numar"]
    total = sum(numere)
    return [round(n * 100 / total) for n in numere] if total else [0] * nr_optiuni


def noteaza_final(motiv: str, arhetip: str | None, nivel: int) -> None:
    with _lacat:
        conexiune().execute(
            "INSERT INTO finaluri (motiv, arhetip, nivel, numar) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(motiv, arhetip, nivel) DO UPDATE SET numar = numar + 1",
            (motiv, arhetip or "", nivel),
        )
        conexiune().commit()


def statistici() -> dict[str, Any]:
    con = conexiune()
    partide = con.execute("SELECT COUNT(*) AS n FROM partide").fetchone()["n"]
    finaluri = [dict(r) for r in con.execute("SELECT motiv, arhetip, nivel, numar FROM finaluri ORDER BY numar DESC")]
    alegeri = [dict(r) for r in con.execute("SELECT situatie, optiune, numar FROM alegeri ORDER BY situatie, optiune")]
    return {"partide_pornite": partide, "finaluri": finaluri, "alegeri": alegeri}
