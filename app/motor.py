"""Motorul jocului: starea unei partide și regulile.

Nu știe nimic de HTTP sau de baza de date. Primește o stare (dict serializabil
în JSON), aplică o acțiune și întoarce ce s-a întâmplat.

Regulile:
- `ani` ani, `trimestre_pe_an` trimestre, `decizii_pe_trimestru` decizii pe trimestru.
- Trei resurse 0..100 (buget, bunăstare angajați, legalitate). Una la 0 = partida s-a terminat.
- Fiecare opțiune aduce profit (mii lei). La finalul anului se face bilanțul:
  profitul anului se adună la profitul total, care dă nivelul firmei (1..10).
  Un an pe minus scade profitul total, deci nivelul poate și să scadă.
- Situațiile se leagă: o opțiune poate deschide situații următoare (intră
  într-o coadă) și poate pune flaguri; o situație sau o opțiune poate cere nivel,
  cărți, flaguri sau situații jucate înainte.
- Următoarea situație: prima din coadă care îndeplinește cerințele; altfel una
  la întâmplare (ponderat cu `greutate`) dintre cele nejucate, eligibile pe anul
  curent și nemarcate `doar_legata`.
- Cărțile speciale intră în inventar când alegi opțiunea care le dă; le poți
  folosi oricând în timpul unei decizii, se consumă și aplică efectul pe loc.
- La final, dacă opțiunile au `teme`, jucătorul e comparat cu arhetipurile.
"""
from __future__ import annotations

import random
from typing import Any

from .continut import RESURSE, Continut

PAS_DECIZIE = "decizie"
PAS_BILANT = "bilant"
PAS_CARTE = "carte"       # doar în istoric: o carte folosită
PAS_FINAL = "final"       # mandat dus la capăt (sau povestea s-a terminat), se poate cere rezultatul
PAS_TERMINAT = "terminat"  # o resursă a ajuns la 0


class ActiuneInvalida(ValueError):
    pass


# ---------------------------------------------------------------- stare

def stare_noua(c: Continut, firma: dict[str, Any], seed: int | None = None) -> dict[str, Any]:
    """Pornește o partidă. `firma` e ce a ales jucătorul (nume, slogan...), netratat."""
    if not c.situatii:
        raise ActiuneInvalida("nu există nicio situație în conținut")
    if seed is None:
        seed = random.SystemRandom().randrange(2**31)
    stare: dict[str, Any] = {
        "firma": firma,
        "seed": seed,
        "resurse": {k: int(v["start"]) for k, v in c.resurse.items()},
        "an": 1,
        "trimestru": 1,          # în anul curent
        "decizia": 1,            # în trimestrul curent
        "profit_an": 0,
        "profit_total": 0,
        "nivel": 1,
        "carti": [],             # inventarul, în ordinea primirii
        "flaguri": [],
        "jucate": [],            # id-urile situațiilor jucate
        "coada": [],             # situații deschise de opțiuni, încă nejucate
        "pas": PAS_DECIZIE,
        "pas_id": None,          # situația curentă
        "istoric": [],
        "final": None,
    }
    _alege_situatia(c, stare)
    return stare


def _rng(stare: dict[str, Any]) -> random.Random:
    """Determinist pentru pasul curent: aceeași stare dă aceeași situație următoare."""
    return random.Random(f"{stare['seed']}:{len(stare['istoric'])}")


# ---------------------------------------------------------------- cerințe

def cerinte_indeplinite(stare: dict[str, Any], cer: dict[str, Any] | None) -> str | None:
    """None dacă totul e în regulă, altfel motivul (text scurt) pentru care e blocat."""
    if not cer:
        return None
    if "nivel_min" in cer and stare["nivel"] < cer["nivel_min"]:
        return f"Nivel {cer['nivel_min']}"
    if "nivel_max" in cer and stare["nivel"] > cer["nivel_max"]:
        return f"Doar până la nivelul {cer['nivel_max']}"
    carti = set(stare["carti"])
    lipsa = [x for x in cer.get("carti", []) if x not in carti]
    if lipsa:
        return "Cere cartea: " + ", ".join(lipsa)
    if any(x in carti for x in cer.get("fara_carti", [])):
        return "Nu se poate cu cartea asta"
    flaguri = set(stare["flaguri"])
    if any(x not in flaguri for x in cer.get("flaguri", [])):
        return "Depinde de o alegere anterioară"
    if any(x in flaguri for x in cer.get("fara_flaguri", [])):
        return "Exclusă de o alegere anterioară"
    jucate = set(stare["jucate"])
    if any(x not in jucate for x in cer.get("dupa", [])):
        return "Vine după altă situație"
    return None


def _in_an(c: Continut, s: dict[str, Any], an: int) -> bool:
    return s.get("an_min", 1) <= an <= s.get("an_max", c.ani)


def _eligibila(c: Continut, stare: dict[str, Any], s: dict[str, Any], din_coada: bool) -> bool:
    if s["id"] in stare["jucate"] and not s.get("repetabila"):
        return False
    if cerinte_indeplinite(stare, s.get("cerinte")) is not None:
        return False
    if not din_coada and (s.get("doar_legata") or not _in_an(c, s, stare["an"])):
        return False
    # Trebuie să existe măcar o opțiune pe care o poate alege.
    return any(cerinte_indeplinite(stare, o.get("cerinte")) is None for o in s["optiuni"])


def _alege_situatia(c: Continut, stare: dict[str, Any]) -> bool:
    """Pune în `pas_id` situația următoare. False dacă nu mai e niciuna."""
    # 1. Coada: ce au deschis alegerile de dinainte, în ordine.
    for id_ in list(stare["coada"]):
        s = c.situatie(id_)
        if _eligibila(c, stare, s, din_coada=True):
            stare["coada"].remove(id_)
            stare["pas_id"] = id_
            return True
    # 2. La întâmplare, ponderat, dintre cele libere pe anul curent.
    libere = [s for s in c.situatii if _eligibila(c, stare, s, din_coada=False)]
    if not libere:
        return False
    rng = _rng(stare)
    ales = rng.choices(libere, weights=[float(s.get("greutate", 1)) for s in libere], k=1)[0]
    stare["pas_id"] = ales["id"]
    return True


# ---------------------------------------------------------------- efecte

def _aplica_resurse(stare: dict[str, Any], ef: dict[str, float]) -> dict[str, int]:
    aplicat: dict[str, int] = {}
    for k in RESURSE:
        d = int(round(ef.get(k, 0)))
        if d == 0:
            continue
        vechi = stare["resurse"][k]
        nou = max(0, min(100, vechi + d))
        stare["resurse"][k] = nou
        aplicat[k] = nou - vechi
    return aplicat


def _verifica_terminat(c: Continut, stare: dict[str, Any]) -> bool:
    for k in RESURSE:
        if stare["resurse"][k] <= 0:
            f = c.finaluri[k]
            stare["final"] = {"motiv": k, "titlu": f["titlu"], "text": f["text"], "mandat_complet": False}
            stare["pas"], stare["pas_id"] = PAS_TERMINAT, None
            return True
    return False


def _incheie(c: Continut, stare: dict[str, Any], motiv: str) -> None:
    f = c.finaluri[motiv]
    stare["final"] = {"motiv": motiv, "titlu": f["titlu"], "text": f["text"], "mandat_complet": motiv == "mandat"}
    stare["pas"], stare["pas_id"] = PAS_FINAL, None


# ---------------------------------------------------------------- acțiuni

def alege(c: Continut, stare: dict[str, Any], optiune: int) -> dict[str, Any]:
    """Jucătorul alege o opțiune la situația curentă."""
    if stare["pas"] != PAS_DECIZIE:
        raise ActiuneInvalida(f"nu e momentul unei alegeri, pasul curent e {stare['pas']!r}")
    s = c.situatie(stare["pas_id"])
    if not isinstance(optiune, int) or not 0 <= optiune < len(s["optiuni"]):
        raise ActiuneInvalida(f"opțiunea {optiune!r} nu există, sunt {len(s['optiuni'])}")
    o = s["optiuni"][optiune]
    blocat = cerinte_indeplinite(stare, o.get("cerinte"))
    if blocat:
        raise ActiuneInvalida(f"opțiunea e blocată: {blocat}")

    delta = _aplica_resurse(stare, o.get("ef", {}))
    profit = o.get("profit", 0)
    stare["profit_an"] += profit

    carte_noua = None
    if o.get("carte"):
        # Aceeași carte poate fi primită la mai multe alegeri; inventarul ține fiecare exemplar.
        stare["carti"].append(o["carte"])
        carte_noua = c.carte(o["carte"])
    for f in o.get("flaguri", []):
        if f not in stare["flaguri"]:
            stare["flaguri"].append(f)
    for urm in o.get("urmatoare", []):
        if urm not in stare["coada"] and urm not in stare["jucate"]:
            stare["coada"].append(urm)
    stare["jucate"].append(s["id"])

    stare["istoric"].append({
        "tip": PAS_DECIZIE, "id": s["id"], "an": stare["an"], "trimestru": stare["trimestru"],
        "optiune": optiune, "delta": delta, "profit": profit, "teme": dict(o.get("teme", {})),
        "carte": o.get("carte"),
    })

    efect = {
        "delta": delta, "profit": profit, "resurse": dict(stare["resurse"]),
        "carte": carte_noua, "teme": dict(o.get("teme", {})),
    }
    if _verifica_terminat(c, stare):
        return efect
    _inainteaza(c, stare)
    return efect


def _inainteaza(c: Continut, stare: dict[str, Any]) -> None:
    """După o decizie: următoarea decizie, trimestru, bilanț sau final."""
    if stare["decizia"] < c.decizii_pe_trimestru:
        stare["decizia"] += 1
    elif stare["trimestru"] < c.trimestre_pe_an:
        stare["trimestru"] += 1
        stare["decizia"] = 1
    else:
        stare["pas"], stare["pas_id"] = PAS_BILANT, None
        return
    if not _alege_situatia(c, stare):
        _incheie(c, stare, "fara_situatii")


def bilant(c: Continut, stare: dict[str, Any]) -> dict[str, Any]:
    """Închide anul: profitul anului intră în total, nivelul se recalculează (poate și scădea). Apoi trece la anul următor sau la final."""
    if stare["pas"] != PAS_BILANT:
        raise ActiuneInvalida(f"nu e momentul bilanțului, pasul curent e {stare['pas']!r}")

    net = stare["profit_an"]

    nivel_vechi = stare["nivel"]
    stare["profit_total"] += net
    nivel_nou = c.nivel_pentru(stare["profit_total"])
    stare["nivel"] = int(nivel_nou["nivel"])

    rezultat = {
        "an": stare["an"], "profit_an": net,
        "profit_total": stare["profit_total"],
        "nivel_vechi": nivel_vechi, "nivel": stare["nivel"], "nivel_nume": nivel_nou["nume"],
        "nivel_desc": nivel_nou.get("desc", ""), "resurse": dict(stare["resurse"]),
    }
    stare["istoric"].append({"tip": PAS_BILANT, **{k: v for k, v in rezultat.items() if k != "resurse"}})
    stare["profit_an"] = 0

    if _verifica_terminat(c, stare):
        return rezultat
    if stare["an"] >= c.ani:
        _incheie(c, stare, "mandat")
        return rezultat
    stare["an"] += 1
    stare["trimestru"], stare["decizia"] = 1, 1
    stare["pas"] = PAS_DECIZIE
    if not _alege_situatia(c, stare):
        _incheie(c, stare, "fara_situatii")
    return rezultat


def foloseste_carte(c: Continut, stare: dict[str, Any], id_carte: str) -> dict[str, Any]:
    """Jucătorul folosește o carte din inventar. Se consumă și efectul se aplică pe loc."""
    if stare["pas"] != PAS_DECIZIE:
        raise ActiuneInvalida(f"cărțile se folosesc în timpul unei decizii, pasul curent e {stare['pas']!r}")
    if id_carte not in stare["carti"]:
        raise ActiuneInvalida(f"nu ai cartea {id_carte!r} în inventar")
    carte = c.carte(id_carte)
    if carte is None:
        raise ActiuneInvalida(f"cartea {id_carte!r} nu mai există în conținut")
    ef = carte.get("efect", {})
    delta = _aplica_resurse(stare, ef)
    profit = ef.get("profit", 0)
    stare["profit_an"] += profit
    stare["carti"].remove(id_carte)
    stare["istoric"].append({"tip": PAS_CARTE, "id": id_carte, "an": stare["an"], "trimestru": stare["trimestru"], "delta": delta, "profit": profit})
    _verifica_terminat(c, stare)
    return {"carte": carte, "delta": delta, "profit": profit, "resurse": dict(stare["resurse"])}


# ---------------------------------------------------------------- rezultat

def pozitii_medii(stare: dict[str, Any]) -> dict[str, float]:
    sume: dict[str, list[float]] = {}
    for i in stare["istoric"]:
        for t, v in i.get("teme", {}).items():
            sume.setdefault(t, []).append(v)
    return {t: round(sum(v) / len(v), 3) for t, v in sume.items()}


def potrivire(c: Continut, stare: dict[str, Any]) -> dict[str, Any]:
    """Cu ce arhetip seamănă jucătorul: 100 − (diferența medie ÷ 4) × 100."""
    poz = pozitii_medii(stare)
    clasament = []
    for a in c.arhetipuri:
        if len(a["poz"]) < c.minim_teme:
            continue
        diferente, la_fel = [], []
        for t, v in poz.items():
            if t in a["poz"]:
                d = abs(v - a["poz"][t])
                diferente.append(d)
                if d <= 0.5:
                    la_fel.append(t)
            else:
                diferente.append(1.0)
        if not diferente:
            continue
        medie = sum(diferente) / len(diferente)
        clasament.append({
            "id": a["id"], "nume": a["nume"], "desc": a.get("desc", ""),
            "procent": round(max(0.0, min(100.0, 100 - medie / 4 * 100)), 1), "teme_la_fel": la_fel,
        })
    clasament.sort(key=lambda x: -x["procent"])
    return {"pozitii": poz, "busola": busola(c, poz), "clasament": clasament, "castigator": clasament[0] if clasament else None}


def busola(c: Continut, poz: dict[str, float]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for cheie, ax in c.axe.items():
        inv = set(ax.get("inverseaza", []))
        valori = [(-poz[t] if t in inv else poz[t]) for t in ax["teme"] if t in poz]
        val = round(sum(valori) / len(valori), 2) if valori else 0.0
        eticheta = ax["minus"] if val <= -0.5 else ax["plus"] if val >= 0.5 else "La mijloc"
        out[cheie] = {"nume": ax.get("nume", cheie), "valoare": val, "eticheta": eticheta}
    return out


def rezultat(c: Continut, stare: dict[str, Any]) -> dict[str, Any]:
    if stare["final"] is None:
        raise ActiuneInvalida("partida nu s-a terminat încă")
    nivel = c.niveluri[stare["nivel"] - 1]
    return {
        "firma": stare["firma"],
        "final": stare["final"],
        "resurse": dict(stare["resurse"]),
        "profit_total": stare["profit_total"],
        "nivel": {"nivel": stare["nivel"], "nume": nivel["nume"], "desc": nivel.get("desc", "")},
        "carti": [c.carte(x) or {"id": x, "nume": x} for x in stare["carti"]],
        "carti_folosite": [i["id"] for i in stare["istoric"] if i["tip"] == PAS_CARTE],
        "ani_jucati": stare["an"] if stare["final"]["mandat_complet"] else stare["an"],
        "decizii": len([i for i in stare["istoric"] if i["tip"] == PAS_DECIZIE]),
        "potrivire": potrivire(c, stare),
    }


# ---------------------------------------------------------------- vedere pentru client

def pas_curent(c: Continut, stare: dict[str, Any]) -> dict[str, Any]:
    """Ce trebuie să afișeze clientul acum. Nu dezvăluie efectele opțiunilor înainte de alegere."""
    pas = stare["pas"]
    nivel = c.niveluri[stare["nivel"] - 1]
    baza: dict[str, Any] = {
        "pas": pas,
        "an": stare["an"], "trimestru": stare["trimestru"], "decizia": stare["decizia"],
        "nr_decizie": len([i for i in stare["istoric"] if i["tip"] == PAS_DECIZIE]) + 1,
        "resurse": dict(stare["resurse"]),
        "profit_an": stare["profit_an"], "profit_total": stare["profit_total"],
        "nivel": {"nivel": stare["nivel"], "nume": nivel["nume"]},
        "carti": [c.carte(x) or {"id": x, "nume": x} for x in stare["carti"]],
    }
    if pas == PAS_DECIZIE:
        s = c.situatie(stare["pas_id"])
        baza.update({
            "id": s["id"], "titlu": s["titlu"], "text": s["text"],
            "optiuni": [
                {"text": o["text"], "blocat": cerinte_indeplinite(stare, o.get("cerinte"))}
                for o in s["optiuni"]
            ],
        })
    elif pas == PAS_BILANT:
        baza["profit_an"] = stare["profit_an"]
    else:
        baza["final"] = stare["final"]
    return baza
