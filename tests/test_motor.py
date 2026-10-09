"""Testele motorului: reguli, legături între situații, nivel, cărți, final."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ["PATRONACHE_DB"] = os.path.join(tempfile.gettempdir(), "patronache-test.db")

from app import continut as modul_continut, motor  # noqa: E402

RADACINA = Path(__file__).resolve().parent.parent


def continut_de_test(**schimbari) -> modul_continut.Continut:
    """Conținut mic și controlat: 2 ani x 1 trimestru x 2 decizii = 4 decizii."""
    brut = {n: modul_continut.citeste_fisier(RADACINA / "continut", n) for n in modul_continut.FISIERE}
    brut = copy.deepcopy(brut)
    brut["config.json"].update({"ani": 2, "trimestre_pe_an": 1, "decizii_pe_trimestru": 2, "profit_de_baza_pe_an": 0})
    brut["niveluri.json"]["niveluri"] = [
        {"nivel": 1, "nume": "Apartament", "prag": 0},
        {"nivel": 2, "nume": "Sediu", "prag": 50},
        {"nivel": 3, "nume": "Mare", "prag": 200},
    ]
    brut["carti.json"]["carti"] = [
        {"id": "pizza", "nume": "Pizza", "efect": {"parteneri": -2, "bunastare": 10}},
    ]

    def sit(id_, nivel=1, **extra):
        return {
            "id": id_, "titlu": id_, "text": "...", "nivel": nivel,
            "optiuni": [
                {"text": "bun", "ef": {"parteneri": 5, "bunastare": 5, "legalitate": 5}, "profit": 30, "teme": {"fisc": -2}},
                {"text": "rau", "ef": {"parteneri": -30, "bunastare": -30, "legalitate": -30}, "profit": -40, "teme": {"fisc": 2}},
            ],
            **extra,
        }

    brut["situatii.json"]["situatii"] = [
        sit("a"), sit("b"), sit("c"), sit("d"), sit("e"), sit("f"),
    ]
    for k, v in schimbari.items():
        brut[k] = v
    return modul_continut.construieste(brut)


class Reguli(unittest.TestCase):
    def test_partida_intreaga_pana_la_final(self):
        c = continut_de_test()
        s = motor.stare_noua(c, {"nume": "Test SRL"}, seed=1)
        self.assertEqual(s["pas"], motor.PAS_DECIZIE)
        self.assertIn(s["pas_id"], {"a", "b", "c", "d", "e", "f"})

        motor.alege(c, s, 0)
        self.assertEqual((s["an"], s["trimestru"], s["decizia"]), (1, 1, 2))
        motor.alege(c, s, 0)
        self.assertEqual(s["pas"], motor.PAS_BILANT)

        b = motor.bilant(c, s)
        self.assertEqual(b["profit_an"], 60)
        self.assertEqual(b["nivel"], 2)        # 60 >= pragul 50
        self.assertEqual(s["an"], 2)
        self.assertEqual(s["pas"], motor.PAS_DECIZIE)

        motor.alege(c, s, 0)
        motor.alege(c, s, 0)
        motor.bilant(c, s)
        self.assertEqual(s["pas"], motor.PAS_FINAL)
        self.assertTrue(s["final"]["mandat_complet"])
        self.assertEqual(len(set(s["jucate"])), 4, "nicio situație nu se repetă")

        r = motor.rezultat(c, s)
        self.assertEqual(r["profit_total"], 120)
        self.assertEqual(r["nivel"]["nivel"], 2)
        self.assertEqual(r["potrivire"]["pozitii"], {"fisc": -2.0})

    def test_profitul_de_baza_intra_la_bilant(self):
        c = continut_de_test()
        c.config["profit_de_baza_pe_an"] = 70
        s = motor.stare_noua(c, {}, seed=1)
        motor.alege(c, s, 0); motor.alege(c, s, 0)
        b = motor.bilant(c, s)
        self.assertEqual((b["profit_alegeri"], b["profit_baza"], b["profit_an"]), (60, 70, 130))
        self.assertEqual(s["profit_total"], 130)

    def test_resursa_la_zero_termina_partida(self):
        c = continut_de_test()
        s = motor.stare_noua(c, {}, seed=1)
        motor.alege(c, s, 1)   # -30 pe toate: 50 -> 20
        self.assertEqual(s["pas"], motor.PAS_DECIZIE)
        motor.alege(c, s, 1)   # 20 -> 0
        self.assertEqual(s["pas"], motor.PAS_TERMINAT)
        self.assertEqual(s["final"]["motiv"], "parteneri")
        self.assertFalse(s["final"]["mandat_complet"])
        self.assertEqual(s["resurse"]["parteneri"], 0)
        with self.assertRaises(motor.ActiuneInvalida):
            motor.alege(c, s, 0)

    def test_fiecare_resursa_la_zero_pierde(self):
        for res in ("parteneri", "bunastare", "legalitate"):
            c = continut_de_test()
            s = motor.stare_noua(c, {}, seed=1)
            s["resurse"][res] = 10
            motor.alege(c, s, 1)
            self.assertEqual(s["final"]["motiv"], res)

    def test_nivelul_scade_cand_profitul_e_pe_minus(self):
        c = continut_de_test()
        s = motor.stare_noua(c, {}, seed=1)
        s["profit_total"], s["nivel"] = 220, 3
        s["resurse"] = {"parteneri": 100, "bunastare": 100, "legalitate": 100}  # să nu pierdem din resurse
        motor.alege(c, s, 1)
        motor.alege(c, s, 1)
        b = motor.bilant(c, s)
        self.assertEqual(b["profit_an"], -80)
        self.assertEqual(b["profit_total"], 140)
        self.assertEqual((b["nivel_vechi"], b["nivel"]), (3, 2))

    def test_resursele_se_opresc_la_100(self):
        c = continut_de_test()
        s = motor.stare_noua(c, {}, seed=1)
        s["resurse"]["parteneri"] = 98
        ef = motor.alege(c, s, 0)
        self.assertEqual(s["resurse"]["parteneri"], 100)
        self.assertEqual(ef["delta"]["parteneri"], 2)

    def test_acelasi_seed_da_aceeasi_partida(self):
        c = continut_de_test()
        a = motor.stare_noua(c, {}, seed=7)
        b = motor.stare_noua(c, {}, seed=7)
        for _ in range(2):
            motor.alege(c, a, 0)
            motor.alege(c, b, 0)
        self.assertEqual(a["jucate"], b["jucate"])


class Legaturi(unittest.TestCase):
    def test_optiunea_deschide_situatia_urmatoare(self):
        c = continut_de_test()
        c.situatii[0]["optiuni"][0]["urmatoare"] = ["f"]
        c.situatii[0]["optiuni"][0]["flaguri"] = ["x"]
        c.situatie("f")["doar_legata"] = True
        c.situatie("f")["cerinte"] = {"flaguri": ["x"]}
        s = motor.stare_noua(c, {}, seed=3)
        s["pas_id"] = "a"
        motor.alege(c, s, 0)
        self.assertEqual(s["pas_id"], "f", "situația deschisă vine imediat")
        self.assertIn("x", s["flaguri"])

    def test_doar_legata_nu_apare_la_intamplare(self):
        c = continut_de_test()
        for id_ in ("b", "c", "d", "e", "f"):
            c.situatie(id_)["doar_legata"] = True
        s = motor.stare_noua(c, {}, seed=5)
        self.assertEqual(s["pas_id"], "a")
        motor.alege(c, s, 0)
        self.assertEqual(s["pas"], motor.PAS_FINAL)
        self.assertEqual(s["final"]["motiv"], "fara_situatii")
        self.assertEqual(s["profit_total"], 30, "profitul anului neterminat intră în total")

    def test_cerinta_de_nivel_pe_situatie(self):
        c = continut_de_test()
        for id_ in ("b", "c", "d", "e", "f"):
            c.situatie(id_)["nivel"] = 2
        s = motor.stare_noua(c, {}, seed=5)
        self.assertEqual(s["pas_id"], "a")
        s["nivel"] = 2
        motor.alege(c, s, 0)
        self.assertNotEqual(s["pas_id"], "a")

    def test_optiune_blocata_de_nivel(self):
        c = continut_de_test()
        c.situatie("a")["optiuni"][1]["cerinte"] = {"nivel_min": 3}
        s = motor.stare_noua(c, {}, seed=1)
        s["pas_id"] = "a"
        pas = motor.pas_curent(c, s)
        self.assertIsNone(pas["optiuni"][0]["blocat"])
        self.assertEqual(pas["optiuni"][1]["blocat"], "Nivel 3")
        with self.assertRaises(motor.ActiuneInvalida):
            motor.alege(c, s, 1)
        s["nivel"] = 3
        self.assertIsNone(motor.pas_curent(c, s)["optiuni"][1]["blocat"])
        motor.alege(c, s, 1)

    def test_cerinta_dupa_si_fara_flaguri(self):
        c = continut_de_test()
        c.situatie("b")["cerinte"] = {"dupa": ["a"]}
        c.situatie("c")["cerinte"] = {"fara_flaguri": ["x"]}
        s = motor.stare_noua(c, {}, seed=1)
        self.assertIsNone(motor.cerinte_indeplinite(s, c.situatie("c")["cerinte"]))
        self.assertEqual(motor.cerinte_indeplinite(s, c.situatie("b")["cerinte"]), "Vine după altă situație")
        s["jucate"].append("a")
        s["flaguri"].append("x")
        self.assertIsNone(motor.cerinte_indeplinite(s, c.situatie("b")["cerinte"]))
        self.assertIsNotNone(motor.cerinte_indeplinite(s, c.situatie("c")["cerinte"]))

    def test_situatiile_apar_de_la_nivelul_lor_in_sus(self):
        c = continut_de_test()
        c.situatie("b")["nivel"] = 2; c.situatie("c")["nivel"] = 2
        for id_ in ("d", "e", "f"):
            c.situatie(id_)["nivel"] = 3
        s = motor.stare_noua(c, {}, seed=2)
        self.assertEqual(s["pas_id"], "a", "la nivelul 1 doar situațiile de nivel 1")
        s["nivel"] = 2
        motor.alege(c, s, 0)
        self.assertIn(s["pas_id"], {"b", "c"}, "la nivelul 2 intră și cele de nivel 2, cele de 3 nu")
        s["nivel"] = 3; s["jucate"] = ["a"]; s["pas_id"] = None
        motor._alege_situatia(c, s)
        self.assertIn(s["pas_id"], {"b", "c", "d", "e", "f"}, "la nivelul 3 primești din 1, 2 și 3")

    def test_avertismente(self):
        c = continut_de_test()
        c.situatie("f")["doar_legata"] = True
        c.situatie("e")["cerinte"] = {"flaguri": ["nimeni-nu-l-pune"]}
        for id_ in ("a", "b", "c", "d"):
            c.situatie(id_)["nivel"] = 3   # la nivelul 1 rămâne doar "e": prea puține pentru 4 decizii
        tipuri = {a["tip"] for a in modul_continut.verifica(c)}
        self.assertIn("neatinsa", tipuri)
        self.assertIn("flag", tipuri)
        self.assertIn("putine", tipuri)


if __name__ == "__main__":
    unittest.main()
