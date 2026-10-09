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
    brut["config.json"].update({"ani": 2, "trimestre_pe_an": 1, "decizii_pe_trimestru": 2, "profit_de_baza_pe_an": 0, "garantie_carte": {"dupa": 0, "reguli": []}})
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

    def test_profitul_de_baza_se_schimba_permanent(self):
        c = continut_de_test()
        c.config["profit_de_baza_pe_an"] = 70
        c.situatie("a")["optiuni"][0]["profit_baza"] = 25
        s = motor.stare_noua(c, {}, seed=1)
        s["pas_id"] = "a"
        ef = motor.alege(c, s, 0)
        self.assertEqual((ef["profit_baza"], ef["profit_baza_total"]), (25, 95))
        self.assertEqual(motor.pas_curent(c, s)["profit_baza"], 95)
        motor.alege(c, s, 0)
        b = motor.bilant(c, s)
        self.assertEqual(b["profit_baza"], 95, "anul 1 e deja afectat")
        motor.alege(c, s, 0); motor.alege(c, s, 0)
        b = motor.bilant(c, s)
        self.assertEqual(b["profit_baza"], 95, "și anii următori, până la final")

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
        self.assertEqual(pas["optiuni"][1]["blocat"], "Cere nivelul 3")
        with self.assertRaises(motor.ActiuneInvalida):
            motor.alege(c, s, 1)
        s["nivel"] = 3
        self.assertIsNone(motor.pas_curent(c, s)["optiuni"][1]["blocat"])
        self.assertIsNone(motor.pas_curent(c, s)["optiuni"][1]["deblocat"], "nivelul nu primește notă")
        c.situatie("a")["optiuni"][1]["cerinte"] = {"flaguri": ["x"]}; s["flaguri"] = ["x"]
        self.assertEqual(motor.pas_curent(c, s)["optiuni"][1]["deblocat"], "Deblocată de o alegere anterioară")
        self.assertIsNone(motor.pas_curent(c, s)["optiuni"][0]["deblocat"], "fără cerințe, fără notă")
        motor.alege(c, s, 1)

    def test_cerinta_dupa_si_fara_flaguri(self):
        c = continut_de_test()
        c.situatie("b")["cerinte"] = {"dupa": ["a"]}
        c.situatie("c")["cerinte"] = {"fara_flaguri": ["x"]}
        s = motor.stare_noua(c, {}, seed=1)
        self.assertIsNone(motor.cerinte_indeplinite(s, c.situatie("c")["cerinte"]))
        self.assertEqual(motor.cerinte_indeplinite(s, c.situatie("b")["cerinte"]), "Venea după altă situație")
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

class Domenii(unittest.TestCase):
    def test_situatiile_si_cartile_respecta_domeniul(self):
        c = continut_de_test()
        c.config["domenii"] = [{"id": "it", "nume": "IT"}, {"id": "horeca", "nume": "Horeca"}]
        for id_ in ("b", "c", "d", "e", "f"):
            c.situatie(id_)["domenii"] = ["horeca"]
        c.carti.append({"id": "vin", "nume": "Vin", "domenii": ["horeca"], "efect": {"bunastare": 5}}); c._carti["vin"] = c.carti[-1]
        c.situatie("a")["optiuni"][0]["carte"] = "vin"
        s = motor.stare_noua(c, {"domeniu": "it"}, seed=1)
        self.assertEqual(s["pas_id"], "a", "doar situația fără domenii e pentru IT")
        motor.alege(c, s, 0)
        self.assertEqual(s["carti"], [], "cartea de horeca nu se dă la IT")
        self.assertEqual(s["final"]["motiv"], "fara_situatii")
        s2 = motor.stare_noua(c, {"domeniu": "horeca"}, seed=1)
        s2["pas_id"] = "a"; motor.alege(c, s2, 0)
        self.assertEqual(s2["carti"], ["vin"])
        self.assertIn(s2["pas_id"], {"b", "c", "d", "e", "f"})

    def test_arhetipurile_respecta_domeniul(self):
        c = continut_de_test()
        c.config["domenii"] = [{"id": "it", "nume": "IT"}, {"id": "horeca", "nume": "Horeca"}]
        c.arhetipuri[:] = [
            {"id": "x", "nume": "General", "poz": {"fisc": -2, "salarii": 0, "control": 0, "risc": 0, "clienti": 0}},
            {"id": "y", "nume": "Restaurant", "domenii": ["horeca"], "poz": {"fisc": -2, "salarii": 0, "control": 0, "risc": 0, "clienti": 0}},
        ]
        s = motor.stare_noua(c, {"domeniu": "it"}, seed=1)
        motor.alege(c, s, 0)
        self.assertEqual([x["id"] for x in motor.potrivire(c, s)["clasament"]], ["x"])
        s2 = motor.stare_noua(c, {"domeniu": "horeca"}, seed=1)
        motor.alege(c, s2, 0)
        self.assertEqual(sorted(x["id"] for x in motor.potrivire(c, s2)["clasament"]), ["x", "y"])

    def test_lista_de_carti_da_prima_potrivita_domeniului(self):
        c = continut_de_test()
        c.config["domenii"] = [{"id": "it", "nume": "IT"}, {"id": "horeca", "nume": "Horeca"}]
        c.carti += [{"id": "cto", "nume": "CTO", "domenii": ["it"], "efect": {"bunastare": -8}},
                    {"id": "om", "nume": "Omul de bază", "domenii": ["horeca"], "efect": {"bunastare": -8}}]
        for x in c.carti[-2:]: c._carti[x["id"]] = x
        c.situatie("a")["optiuni"][0]["carte"] = ["om", "cto"]
        for dom, asteptat in (("it", "cto"), ("horeca", "om")):
            s = motor.stare_noua(c, {"domeniu": dom}, seed=1); s["pas_id"] = "a"
            ef = motor.alege(c, s, 0)
            self.assertEqual(s["carti"], [asteptat]); self.assertEqual(ef["carte"]["id"], asteptat)

    def test_domeniu_necunoscut_devine_primul(self):
        c = continut_de_test()
        c.config["domenii"] = [{"id": "it", "nume": "IT"}]
        s = motor.stare_noua(c, {"domeniu": "ceva"}, seed=1)
        self.assertEqual(s["firma"]["domeniu"], "it")


class Carti(unittest.TestCase):
    def test_cartea_intra_in_inventar_si_se_foloseste(self):
        c = continut_de_test()
        c.situatie("a")["optiuni"][0]["carte"] = "pizza"
        s = motor.stare_noua(c, {}, seed=1)
        s["pas_id"] = "a"
        ef = motor.alege(c, s, 0)
        self.assertEqual(ef["carte"]["id"], "pizza")
        self.assertEqual(s["carti"], ["pizza"])
        self.assertEqual([x["id"] for x in motor.pas_curent(c, s)["carti"]], ["pizza"])

        bun = s["resurse"]["bunastare"]
        r = motor.foloseste_carte(c, s, "pizza")
        self.assertEqual(r["delta"], {"parteneri": -2, "bunastare": 10})
        self.assertEqual(s["resurse"]["bunastare"], bun + 10)
        self.assertEqual(s["carti"], [], "cartea s-a consumat")
        with self.assertRaises(motor.ActiuneInvalida):
            motor.foloseste_carte(c, s, "pizza")

    def test_aceeasi_carte_de_mai_multe_ori(self):
        c = continut_de_test()
        c.situatie("a")["optiuni"][0]["carte"] = "pizza"
        c.situatie("b")["optiuni"][0]["carte"] = "pizza"
        s = motor.stare_noua(c, {}, seed=1)
        s["pas_id"] = "a"; motor.alege(c, s, 0)
        s["carti"].append("pizza")   # ca și cum ar fi primit-o și la o alegere anterioară
        self.assertEqual(s["carti"], ["pizza", "pizza"])
        motor.foloseste_carte(c, s, "pizza")
        self.assertEqual(s["carti"], ["pizza"], "se consumă un singur exemplar")
        s["pas_id"] = "b"; motor.alege(c, s, 0)
        self.assertEqual(s["carti"], ["pizza", "pizza"], "o primește din nou deși o are deja")

    def test_scutul_sare_decizia_curenta_si_opreste_scaderea_la_urmatoarea(self):
        c = continut_de_test()
        c.carti.append({"id": "scut", "nume": "Scut", "efect": {"scut": {"resurse": ["bunastare"], "decizii": 1}}})
        c._carti["scut"] = c.carti[-1]
        s = motor.stare_noua(c, {}, seed=1)
        s["carti"] = ["scut"]
        r = motor.foloseste_carte(c, s, "scut")
        self.assertEqual(r["scut"]["resurse"], ["bunastare"])
        self.assertFalse(motor.pas_curent(c, s)["scuturi"][0]["activ_acum"], "nu se aplică la situația pe care o vezi")
        ef = motor.alege(c, s, 1)   # opțiunea „rea”: -30 pe toate
        self.assertEqual(ef["delta"]["bunastare"], -30, "decizia curentă nu e protejată")
        self.assertEqual(ef["scut_oprit"], {})
        self.assertTrue(motor.pas_curent(c, s)["scuturi"][0]["activ_acum"])
        s["resurse"] = {"parteneri": 90, "bunastare": 90, "legalitate": 90}
        ef = motor.alege(c, s, 1)
        self.assertEqual(ef["delta"].get("bunastare", 0), 0, "următoarea decizie e protejată")
        self.assertEqual(ef["delta"]["parteneri"], -30, "celelalte resurse nu")
        self.assertEqual(ef["scut_oprit"], {"bunastare": -30})
        self.assertEqual(s["scuturi"], [], "scutul s-a consumat")

    def test_cartea_surpriza_isi_ascunde_efectul_pana_e_folosita(self):
        c = continut_de_test()
        c.carti.append({"id": "plic", "nume": "Plicul", "surpriza": True, "desc": "secret", "efect": {"profit": 40, "legalitate": -6}})
        c._carti["plic"] = c.carti[-1]
        c.situatie("a")["optiuni"][0]["carte"] = "plic"
        s = motor.stare_noua(c, {}, seed=1)
        s["pas_id"] = "a"
        ef = motor.alege(c, s, 0)
        self.assertEqual(ef["carte"]["nume"], "Carte surpriză")
        self.assertTrue(ef["carte"]["id"].startswith("surpriza-"), "id-ul real nu se vede")
        vazuta = motor.pas_curent(c, s)["carti"][0]
        self.assertNotIn("efect", vazuta); self.assertNotIn("desc", vazuta); self.assertNotIn("Plic", vazuta["nume"])
        self.assertEqual(vazuta["id"], ef["carte"]["id"], "același cod opac de fiecare dată")
        r = motor.foloseste_carte(c, s, vazuta["id"])   # folosită prin codul opac
        self.assertEqual(r["carte"]["efect"], {"profit": 40, "legalitate": -6}, "la folosire se dezvăluie")
        self.assertEqual(r["delta"], {"legalitate": -6})

    def test_o_alegere_poate_lua_o_carte_vizibila_dar_nu_surpriza(self):
        c = continut_de_test()
        c.carti.append({"id": "plic", "nume": "Plicul", "surpriza": True, "efect": {"profit": 40}}); c._carti["plic"] = c.carti[-1]
        c.situatie("a")["optiuni"][0]["ia_carte"] = "oricare"
        c.situatie("b")["optiuni"][0]["ia_carte"] = "pizza"
        s = motor.stare_noua(c, {}, seed=1)
        s["carti"] = ["plic"]
        s["pas_id"] = "a"; ef = motor.alege(c, s, 0)
        self.assertIsNone(ef["carte_luata"]); self.assertEqual(s["carti"], ["plic"], "surpriza nu se ia")
        s["carti"] = ["plic", "pizza"]
        s["pas_id"] = "b"; ef = motor.alege(c, s, 0)
        self.assertEqual(ef["carte_luata"]["id"], "pizza"); self.assertEqual(s["carti"], ["plic"])

    def test_garantia_de_carte_dupa_decizii_fara_nimic(self):
        c = continut_de_test()
        c.carti += [{"id": "proces", "nume": "Citația", "surpriza": True, "efect": {"legalitate": -6}},
                    {"id": "premiu", "nume": "Premiul", "surpriza": True, "efect": {"bunastare": 4}}]
        for x in c.carti[-2:]: c._carti[x["id"]] = x
        c.config["garantie_carte"] = {"dupa": 2, "reguli": [{"cand": "legalitate_scade", "carti": ["proces"]}, {"cand": "oricand", "carti": ["premiu"]}]}
        s = motor.stare_noua(c, {}, seed=1)
        s["resurse"] = {"parteneri": 100, "bunastare": 100, "legalitate": 100}
        ids = iter(["a", "b", "c", "d"])
        s["pas_id"] = next(ids); ef1 = motor.alege(c, s, 0)   # 1 fără carte
        s["pas_id"] = next(ids); ef2 = motor.alege(c, s, 0)   # 2 fără carte
        self.assertIsNone(ef1["carte"]); self.assertIsNone(ef2["carte"])
        s["pas"] = motor.PAS_DECIZIE; s["pas_id"] = next(ids)
        ef3 = motor.alege(c, s, 1)                              # a 3-a: opțiunea „rea” scade legalitatea -> Citația
        self.assertNotIn("carte_garantata", ef3, "jucătorul nu află că a fost garantată")
        self.assertEqual(s["carti"], ["proces"]); self.assertTrue(s["istoric"][-1]["carte_garantata"])
        self.assertEqual(s["fara_carte"], 0, "contorul se resetează")

    def test_situatia_conditionata_de_resurse(self):
        c = continut_de_test()
        c.situatie("f")["cerinte"] = {"resurse": {"legalitate": {"max": 25}}}
        s = motor.stare_noua(c, {}, seed=1)
        self.assertEqual(motor.cerinte_indeplinite(s, c.situatie("f")["cerinte"]), "Apare doar cu legalitate sub 25")
        s["resurse"]["legalitate"] = 20
        self.assertIsNone(motor.cerinte_indeplinite(s, c.situatie("f")["cerinte"]))

    def test_cartea_nu_se_poate_folosi_la_bilant(self):
        c = continut_de_test()
        s = motor.stare_noua(c, {}, seed=1)
        s["carti"] = ["pizza"]
        motor.alege(c, s, 0)
        motor.alege(c, s, 0)
        self.assertEqual(s["pas"], motor.PAS_BILANT)
        with self.assertRaises(motor.ActiuneInvalida):
            motor.foloseste_carte(c, s, "pizza")


class Validare(unittest.TestCase):
    def test_continutul_din_repo_e_valid(self):
        c = modul_continut.incarca(RADACINA / "continut")
        self.assertGreater(len(c.situatii), 0)
        self.assertEqual(len(c.niveluri), 4)

    def test_legatura_moarta_e_respinsa(self):
        with self.assertRaises(modul_continut.ContinutInvalid) as cm:
            c = continut_de_test()
            c.situatii[0]["optiuni"][0]["urmatoare"] = ["nu-exista"]
            modul_continut.construieste({
                "config.json": c.config, "niveluri.json": {"niveluri": c.niveluri}, "carti.json": {"carti": c.carti},
                "situatii.json": {"situatii": c.situatii}, "arhetipuri.json": {"arhetipuri": c.arhetipuri},
            })
        self.assertIn("nu-exista", str(cm.exception))

    def test_cartea_necunoscuta_e_respinsa(self):
        c = continut_de_test()
        c.situatii[0]["optiuni"][0]["carte"] = "nu-exista"
        with self.assertRaises(modul_continut.ContinutInvalid):
            modul_continut.construieste({
                "config.json": c.config, "niveluri.json": {"niveluri": c.niveluri}, "carti.json": {"carti": c.carti},
                "situatii.json": {"situatii": c.situatii}, "arhetipuri.json": {"arhetipuri": c.arhetipuri},
            })

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
