"""Încarcă și validează conținutul jocului din continut/*.json.

Conținutul e date, nu cod: situațiile, cărțile, nivelurile și arhetipurile se
schimbă din meniul de admin fără să atingi motorul. Validarea e strictă, ca o
greșeală să cadă la salvare sau la pornire, nu în mijlocul unei partide.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RADACINA = Path(__file__).resolve().parent.parent
DIR_CONTINUT_IMPLICIT = RADACINA / "continut"

FISIERE = ("config.json", "niveluri.json", "carti.json", "situatii.json", "arhetipuri.json")
RESURSE = ("parteneri", "bunastare", "legalitate")
FACTOR_BUGET_IN_PROFIT = 5   # la migrare: un punct de „buget” din vechiul model = 5 mii lei profit
CHEI_CERINTE = {"nivel_min", "nivel_max", "carti", "fara_carti", "flaguri", "fara_flaguri", "dupa"}


class ContinutInvalid(ValueError):
    pass


@dataclass
class Continut:
    config: dict[str, Any]
    niveluri: list[dict[str, Any]]
    carti: list[dict[str, Any]]
    situatii: list[dict[str, Any]]
    arhetipuri: list[dict[str, Any]]
    minim_teme: int = 5
    _situatii: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    _carti: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._situatii = {s["id"]: s for s in self.situatii}
        self._carti = {c["id"]: c for c in self.carti}

    # --- reguli generale
    @property
    def ani(self) -> int:
        return int(self.config["ani"])

    @property
    def trimestre_pe_an(self) -> int:
        return int(self.config["trimestre_pe_an"])

    @property
    def decizii_pe_trimestru(self) -> int:
        return int(self.config["decizii_pe_trimestru"])

    @property
    def decizii_pe_an(self) -> int:
        return self.trimestre_pe_an * self.decizii_pe_trimestru

    @property
    def resurse(self) -> dict[str, dict[str, Any]]:
        return self.config["resurse"]

    @property
    def finaluri(self) -> dict[str, dict[str, str]]:
        return self.config["finaluri"]

    @property
    def teme(self) -> dict[str, dict[str, str]]:
        return {k: v for k, v in self.config.get("teme", {}).items() if not k.startswith("_")}

    @property
    def axe(self) -> dict[str, dict[str, Any]]:
        return self.config.get("axe", {})

    def situatie(self, id_: str) -> dict[str, Any]:
        return self._situatii[id_]

    def carte(self, id_: str) -> dict[str, Any] | None:
        return self._carti.get(id_)

    def nivel_pentru(self, profit_total: float) -> dict[str, Any]:
        atins = self.niveluri[0]
        for n in self.niveluri:
            if profit_total >= n["prag"]:
                atins = n
        return atins

    def public(self) -> dict[str, Any]:
        """Ce poate vedea clientul jocului: reguli, resurse, niveluri, cărți, arhetipuri (fără poziții)."""
        return {
            "ani": self.ani,
            "trimestre_pe_an": self.trimestre_pe_an,
            "decizii_pe_trimestru": self.decizii_pe_trimestru,
            "resurse": self.resurse,
            "niveluri": self.niveluri,
            # cărțile surpriză nu apar deloc în lista publică: nici numele n-ar trebui să se vadă
            "carti": [c for c in self.carti if not c.get("surpriza")],
            "carti_surpriza": sum(1 for c in self.carti if c.get("surpriza")),
            "teme": self.teme,
            "axe": {k: {kk: vv for kk, vv in v.items() if kk != "inverseaza"} for k, v in self.axe.items()},
            "arhetipuri": [{"id": a["id"], "nume": a["nume"], "desc": a.get("desc", "")} for a in self.arhetipuri],
            "situatii": len(self.situatii),
        }


# ---------------------------------------------------------------- migrare

def migreaza(brut: dict[str, dict[str, Any]]) -> bool:
    """Aduce conținutul scris pentru modelul vechi (resursa „buget”) la cel nou (resursa „parteneri”,
    efectele de buget trec în profit). Întoarce True dacă a schimbat ceva."""
    schimbat = False
    cfg = brut.get("config.json", {})
    res = cfg.get("resurse", {})
    if "buget" in res and "parteneri" not in res:
        res["parteneri"] = {"nume": "Parteneri", "start": res["buget"].get("start", 50)}
        del res["buget"]
        cfg["resurse"] = {k: res[k] for k in ("parteneri", "bunastare", "legalitate") if k in res} | {k: v for k, v in res.items() if k not in RESURSE}
        schimbat = True
    fin = cfg.get("finaluri", {})
    if "buget" in fin and "parteneri" not in fin:
        fin["parteneri"] = {"titlu": "Partenerii au plecat", "text": "Furnizorii nu mai livrează, clienții nu mai sună. Ai o firmă, dar n-ai cu cine."}
        del fin["buget"]
        schimbat = True

    def muta_ef(o: dict[str, Any]) -> None:
        nonlocal schimbat
        ef = o.get("ef")
        if isinstance(ef, dict) and "buget" in ef:
            o["profit"] = o.get("profit", 0) + ef.pop("buget") * FACTOR_BUGET_IN_PROFIT
            if not o["profit"]:
                del o["profit"]
            if not ef:
                del o["ef"]
            schimbat = True

    for sit in brut.get("situatii.json", {}).get("situatii", []):
        for o in sit.get("optiuni", []):
            muta_ef(o)
    for carte in brut.get("carti.json", {}).get("carti", []):
        ef = carte.get("efect")
        if isinstance(ef, dict):
            if "buget" in ef:
                ef["profit"] = ef.get("profit", 0) + ef.pop("buget") * FACTOR_BUGET_IN_PROFIT
                if not ef["profit"]:
                    del ef["profit"]
                schimbat = True
            scut = ef.get("scut")
            if isinstance(scut, dict) and "buget" in scut.get("resurse", []):
                scut["resurse"] = ["parteneri" if r == "buget" else r for r in scut["resurse"]]
                schimbat = True
    return schimbat


# ---------------------------------------------------------------- citire

def citeste_fisier(director: Path, nume: str) -> dict[str, Any]:
    cale = director / nume
    try:
        return json.loads(cale.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ContinutInvalid(f"lipsește {cale}")
    except json.JSONDecodeError as e:
        raise ContinutInvalid(f"{nume}: JSON invalid: {e}")


def incarca(director: Path | str | None = None) -> Continut:
    director = Path(director) if director else DIR_CONTINUT_IMPLICIT
    brut = {nume: citeste_fisier(director, nume) for nume in FISIERE}
    if migreaza(brut) and director != DIR_CONTINUT_IMPLICIT:
        # conținut scris pentru modelul vechi: îl scriem înapoi migrat, ca admin-ul să vadă același lucru
        for nume, corp in brut.items():
            (director / nume).write_text(json.dumps(corp, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return construieste(brut)


def construieste(brut: dict[str, dict[str, Any]]) -> Continut:
    """Construiește și validează conținutul din dict-urile celor 5 fișiere."""
    config = brut["config.json"]
    _valideaza_config(config)
    teme = {k: v for k, v in config.get("teme", {}).items() if not k.startswith("_")}

    niveluri = brut["niveluri.json"].get("niveluri", [])
    _valideaza_niveluri(niveluri)

    carti = brut["carti.json"].get("carti", [])
    ids_carti = _valideaza_carti(carti)

    situatii = brut["situatii.json"].get("situatii", [])
    _valideaza_situatii(situatii, ids_carti, teme, len(niveluri))

    arhetipuri = brut["arhetipuri.json"].get("arhetipuri", [])
    _valideaza_arhetipuri(arhetipuri, teme)

    return Continut(
        config=config, niveluri=niveluri, carti=carti, situatii=situatii, arhetipuri=arhetipuri,
        minim_teme=int(brut["arhetipuri.json"].get("minim_teme", 5)),
    )


# ---------------------------------------------------------------- validare

def _numar(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _valideaza_config(c: dict[str, Any]) -> None:
    for cheie in ("ani", "trimestre_pe_an", "decizii_pe_trimestru"):
        if not isinstance(c.get(cheie), int) or c[cheie] < 1:
            raise ContinutInvalid(f"config: '{cheie}' trebuie să fie un întreg >= 1")
    res = c.get("resurse")
    if not isinstance(res, dict) or set(res) != set(RESURSE):
        raise ContinutInvalid(f"config: 'resurse' trebuie să aibă exact cheile {RESURSE}")
    for k, v in res.items():
        if not _numar(v.get("start")) or not 0 < v["start"] <= 100:
            raise ContinutInvalid(f"config: resursa {k!r} are nevoie de 'start' în 1..100")
    fin = c.get("finaluri", {})
    for k in (*RESURSE, "mandat", "fara_situatii"):
        if k not in fin or "titlu" not in fin[k]:
            raise ContinutInvalid(f"config: lipsește finalul {k!r}")
    teme = {k: v for k, v in c.get("teme", {}).items() if not k.startswith("_")}
    for ax in c.get("axe", {}).values():
        for t in ax.get("teme", []):
            if t not in teme:
                raise ContinutInvalid(f"config: axa folosește tema necunoscută {t!r}")


def _valideaza_niveluri(niveluri: list[dict[str, Any]]) -> None:
    if not niveluri:
        raise ContinutInvalid("niveluri: lipsesc")
    prag_anterior = None
    for i, n in enumerate(niveluri, start=1):
        if n.get("nivel") != i:
            raise ContinutInvalid(f"niveluri: nivelul de pe poziția {i} trebuie să aibă 'nivel': {i}")
        if "nume" not in n or not _numar(n.get("prag")):
            raise ContinutInvalid(f"niveluri: nivelul {i} are nevoie de 'nume' și 'prag'")
        if prag_anterior is not None and n["prag"] <= prag_anterior:
            raise ContinutInvalid(f"niveluri: pragul nivelului {i} trebuie să fie mai mare decât al nivelului {i - 1}")
        prag_anterior = n["prag"]
    if niveluri[0]["prag"] != 0:
        raise ContinutInvalid("niveluri: nivelul 1 trebuie să aibă prag 0")


def _valideaza_carti(carti: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for c in carti:
        unde = f"cartea {c.get('id', '?')!r}"
        if not c.get("id") or not c.get("nume"):
            raise ContinutInvalid(f"{unde}: trebuie 'id' și 'nume'")
        if c["id"] in ids:
            raise ContinutInvalid(f"{unde}: id duplicat")
        ids.add(c["id"])
        ef = c.get("efect", {})
        if not isinstance(ef, dict):
            raise ContinutInvalid(f"{unde}: 'efect' trebuie să fie dict")
        for k, v in ef.items():
            if k == "scut":
                if not isinstance(v, dict) or not isinstance(v.get("resurse"), list) or not v["resurse"] \
                        or any(r not in RESURSE for r in v["resurse"]) \
                        or ("decizii" in v and (not isinstance(v["decizii"], int) or v["decizii"] < 1)):
                    raise ContinutInvalid(f"{unde}: 'scut' trebuie să fie {{'resurse': [...din {RESURSE}], 'decizii': >= 1}}")
                continue
            if k not in (*RESURSE, "profit") or not _numar(v):
                raise ContinutInvalid(f"{unde}: 'efect' acceptă doar {RESURSE}, 'profit' și 'scut'")
    return ids


def _valideaza_cerinte(cer: Any, unde: str, ids_carti: set[str], nr_niveluri: int) -> None:
    if cer is None:
        return
    if not isinstance(cer, dict):
        raise ContinutInvalid(f"{unde}: 'cerinte' trebuie să fie dict")
    for k in cer:
        if k not in CHEI_CERINTE:
            raise ContinutInvalid(f"{unde}: cerință necunoscută {k!r}; permise: {sorted(CHEI_CERINTE)}")
    for k in ("nivel_min", "nivel_max"):
        if k in cer and (not isinstance(cer[k], int) or not 1 <= cer[k] <= nr_niveluri):
            raise ContinutInvalid(f"{unde}: '{k}' trebuie să fie între 1 și {nr_niveluri}")
    for k in ("carti", "fara_carti"):
        for c in cer.get(k, []):
            if c not in ids_carti:
                raise ContinutInvalid(f"{unde}: cartea necunoscută {c!r} în '{k}'")
    for k in ("flaguri", "fara_flaguri", "dupa"):
        if k in cer and not (isinstance(cer[k], list) and all(isinstance(x, str) for x in cer[k])):
            raise ContinutInvalid(f"{unde}: '{k}' trebuie să fie listă de text")


def _valideaza_situatii(situatii: list[dict[str, Any]], ids_carti: set[str], teme: dict[str, Any], nr_niveluri: int) -> None:
    ids: set[str] = set()
    for s in situatii:
        unde = f"situația {s.get('id', '?')!r}"
        for cheie in ("id", "titlu", "text", "optiuni"):
            if not s.get(cheie):
                raise ContinutInvalid(f"{unde}: lipsește '{cheie}'")
        if s["id"] in ids:
            raise ContinutInvalid(f"{unde}: id duplicat")
        ids.add(s["id"])
        for k in ("an_min", "an_max"):
            if k in s and (not isinstance(s[k], int) or s[k] < 1):
                raise ContinutInvalid(f"{unde}: '{k}' trebuie să fie întreg >= 1")
        if "greutate" in s and (not _numar(s["greutate"]) or s["greutate"] <= 0):
            raise ContinutInvalid(f"{unde}: 'greutate' trebuie să fie > 0")
        _valideaza_cerinte(s.get("cerinte"), unde, ids_carti, nr_niveluri)
        if not (isinstance(s["optiuni"], list) and 2 <= len(s["optiuni"]) <= 4):
            raise ContinutInvalid(f"{unde}: între 2 și 4 opțiuni")
        for i, o in enumerate(s["optiuni"]):
            u = f"{unde}, opțiunea {i + 1}"
            if not o.get("text"):
                raise ContinutInvalid(f"{u}: lipsește 'text'")
            ef = o.get("ef", {})
            if not isinstance(ef, dict) or any(k not in RESURSE or not _numar(v) for k, v in ef.items()):
                raise ContinutInvalid(f"{u}: 'ef' trebuie să aibă chei din {RESURSE} și valori numerice")
            if "profit" in o and not _numar(o["profit"]):
                raise ContinutInvalid(f"{u}: 'profit' trebuie să fie număr")
            if o.get("carte") and o["carte"] not in ids_carti:
                raise ContinutInvalid(f"{u}: cartea necunoscută {o['carte']!r}")
            for k in ("flaguri", "urmatoare"):
                if k in o and not (isinstance(o[k], list) and all(isinstance(x, str) for x in o[k])):
                    raise ContinutInvalid(f"{u}: '{k}' trebuie să fie listă de text")
            t = o.get("teme", {})
            if not isinstance(t, dict) or any(k not in teme or not _numar(v) or not -2 <= v <= 2 for k, v in t.items()):
                raise ContinutInvalid(f"{u}: 'teme' trebuie să aibă chei din teme și valori în -2..+2")
            _valideaza_cerinte(o.get("cerinte"), u, ids_carti, nr_niveluri)
    # Legăturile trebuie să ducă undeva.
    for s in situatii:
        for i, o in enumerate(s["optiuni"]):
            for urm in o.get("urmatoare", []):
                if urm not in ids:
                    raise ContinutInvalid(f"situația {s['id']!r}, opțiunea {i + 1}: 'urmatoare' duce la situația inexistentă {urm!r}")
        for d in (s.get("cerinte") or {}).get("dupa", []):
            if d not in ids:
                raise ContinutInvalid(f"situația {s['id']!r}: 'dupa' cere situația inexistentă {d!r}")


def _valideaza_arhetipuri(arhetipuri: list[dict[str, Any]], teme: dict[str, Any]) -> None:
    ids: set[str] = set()
    for a in arhetipuri:
        unde = f"arhetipul {a.get('id', '?')!r}"
        if not a.get("id") or not a.get("nume") or not isinstance(a.get("poz"), dict):
            raise ContinutInvalid(f"{unde}: trebuie 'id', 'nume' și 'poz'")
        if a["id"] in ids:
            raise ContinutInvalid(f"{unde}: id duplicat")
        ids.add(a["id"])
        for t, v in a["poz"].items():
            if t not in teme or not _numar(v) or not -2 <= v <= 2:
                raise ContinutInvalid(f"{unde}: poziția pe {t!r} trebuie să fie pe o temă existentă, în -2..+2")


# ---------------------------------------------------------------- verificări pentru admin (avertismente, nu erori)

def verifica(c: Continut) -> list[dict[str, str]]:
    """Avertismente despre conținut: situații puține pe un an, legături moarte, situații de neatins."""
    avertismente: list[dict[str, str]] = []
    necesare = c.decizii_pe_an

    # Câte situații pot apărea la întâmplare în fiecare an (fără cele doar legate).
    for an in range(1, c.ani + 1):
        n = sum(
            1 for s in c.situatii
            if not s.get("doar_legata") and s.get("an_min", 1) <= an <= s.get("an_max", c.ani)
        )
        if n < necesare:
            avertismente.append({
                "tip": "putine", "id": f"an-{an}",
                "mesaj": f"Anul {an}: doar {n} situații pot apărea la întâmplare, sunt nevoie de {necesare}. Partida se poate termina devreme.",
            })

    # Situații marcate 'doar_legata' pe care nu le deschide nimeni.
    deschise = {u for s in c.situatii for o in s["optiuni"] for u in o.get("urmatoare", [])}
    for s in c.situatii:
        if s.get("doar_legata") and s["id"] not in deschise:
            avertismente.append({"tip": "neatinsa", "id": s["id"], "mesaj": f"Situația {s['id']!r} e 'doar legată', dar nicio opțiune nu duce la ea."})

    # Flaguri cerute pe care nu le pune nimeni.
    puse = {f for s in c.situatii for o in s["optiuni"] for f in o.get("flaguri", [])}
    for s in c.situatii:
        for f in (s.get("cerinte") or {}).get("flaguri", []):
            if f not in puse:
                avertismente.append({"tip": "flag", "id": s["id"], "mesaj": f"Situația {s['id']!r} cere flagul {f!r}, dar nicio opțiune nu îl pune."})
        for o in s["optiuni"]:
            for f in (o.get("cerinte") or {}).get("flaguri", []):
                if f not in puse:
                    avertismente.append({"tip": "flag", "id": s["id"], "mesaj": f"O opțiune din {s['id']!r} cere flagul {f!r}, dar nicio opțiune nu îl pune."})

    # Cărți cerute pe care nu le dă nimeni.
    date = {o["carte"] for s in c.situatii for o in s["optiuni"] if o.get("carte")}
    for s in c.situatii:
        cerute = set((s.get("cerinte") or {}).get("carti", []))
        for o in s["optiuni"]:
            cerute |= set((o.get("cerinte") or {}).get("carti", []))
        for carte in cerute - date:
            avertismente.append({"tip": "carte", "id": s["id"], "mesaj": f"Situația {s['id']!r} cere cartea {carte!r}, dar nicio opțiune nu o dă."})

    # Opțiuni la care nimeni nu poate ajunge pentru că toate opțiunile sunt blocate.
    for s in c.situatii:
        if all(o.get("cerinte") for o in s["optiuni"]):
            avertismente.append({"tip": "blocata", "id": s["id"], "mesaj": f"Toate opțiunile din {s['id']!r} au cerințe; jucătorul poate rămâne fără nicio variantă."})

    return avertismente
