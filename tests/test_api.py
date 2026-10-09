"""Testele API-ului: o partidă prin HTTP și meniul de admin (scrie într-o copie a conținutului)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

RADACINA = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="patronache-"))
os.environ["PATRONACHE_DB"] = str(TMP / "test.db")
os.environ["PATRONACHE_CONTINUT"] = str(TMP / "continut")
os.environ["PATRONACHE_ADMIN_PAROLA"] = "secret"
shutil.copytree(RADACINA / "continut", TMP / "continut")

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402


class API(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_sanatate_si_continut(self):
        r = self.client.get("/sanatate")
        self.assertTrue(r.json()["ok"])
        r = self.client.get("/api/continut")
        d = r.json()
        self.assertEqual(set(d["resurse"]), {"parteneri", "bunastare", "legalitate"})
        self.assertEqual(len(d["niveluri"]), 4)
        self.assertEqual(len(d["domenii"]), 6)
        self.assertTrue(all("efect" in c and not c.get("surpriza") for c in d["carti"]), "cărțile surpriză nu apar în lista publică")
        self.assertGreater(d["carti_surpriza"], 0, "exemplele au și surprize")

    def test_partida_prin_http(self):
        r = self.client.post("/api/partida", json={"nume": "Test SRL", "slogan": "merge", "domeniu": "horeca"})
        self.assertEqual(r.status_code, 201)
        id_ = r.json()["id"]
        pas = r.json()["pas"]
        self.assertEqual(pas["pas"], "decizie")
        self.assertEqual(len(pas["optiuni"]) >= 2, True)
        self.assertNotIn("ef", pas["optiuni"][0], "efectele nu se văd înainte de alegere")

        # o opțiune blocată nu poate fi aleasă
        libera = next(i for i, o in enumerate(pas["optiuni"]) if not o["blocat"])
        r = self.client.post(f"/api/partida/{id_}/alege", json={"optiune": libera})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertIn("delta", d["efect"])
        self.assertEqual(len(d["efect"]["procente"]), len(pas["optiuni"]))
        self.assertEqual(sum(d["efect"]["procente"]), 100)

        # bilanțul nu merge în mijlocul anului
        r = self.client.post(f"/api/partida/{id_}/bilant")
        self.assertEqual(r.status_code, 409)
        # rezultatul nu e disponibil înainte de final
        r = self.client.get(f"/api/partida/{id_}/rezultat")
        self.assertEqual(r.status_code, 409)
        # opțiune inexistentă
        r = self.client.post(f"/api/partida/{id_}/alege", json={"optiune": 9})
        self.assertEqual(r.status_code, 422)

        # jucăm până la final, mereu prima opțiune liberă, folosim cărțile când le avem
        for _ in range(200):
            pas = self.client.get(f"/api/partida/{id_}").json()["pas"]
            if pas["pas"] == "decizie":
                if pas["carti"]:
                    r = self.client.post(f"/api/partida/{id_}/carte", json={"carte": pas["carti"][0]["id"]})
                    self.assertEqual(r.status_code, 200, r.text)
                    continue
                libera = next(i for i, o in enumerate(pas["optiuni"]) if not o["blocat"])
                r = self.client.post(f"/api/partida/{id_}/alege", json={"optiune": libera})
                self.assertEqual(r.status_code, 200, r.text)
            elif pas["pas"] == "bilant":
                r = self.client.post(f"/api/partida/{id_}/bilant")
                self.assertEqual(r.status_code, 200, r.text)
                self.assertIn("nivel", r.json()["bilant"])
            else:
                break
        self.assertIn(pas["pas"], ("final", "terminat"))
        r = self.client.get(f"/api/partida/{id_}/rezultat")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertIn("nivel", d)
        self.assertIn("potrivire", d)
        self.assertEqual(d["firma"]["nume"], "Test SRL")
        self.assertEqual(d["firma"]["domeniu"], "horeca")

        r = self.client.delete(f"/api/partida/{id_}")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.client.get(f"/api/partida/{id_}").status_code, 404)

    def test_admin_cere_parola(self):
        self.assertEqual(self.client.get("/api/admin/continut").status_code, 401)
        r = self.client.get("/api/admin/continut", headers={"X-Parola": "secret"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("situatii.json", r.json())

    def test_admin_salveaza_si_reincarca(self):
        h = {"X-Parola": "secret"}
        sit = self.client.get("/api/admin/continut", headers=h).json()["situatii.json"]
        noua = {
            "id": "test-noua", "titlu": "Situație nouă", "text": "din test", "an_min": 1, "an_max": 4,
            "optiuni": [
                {"text": "da", "ef": {"parteneri": 1}, "profit": 5, "urmatoare": [sit["situatii"][0]["id"]]},
                {"text": "nu", "ef": {"parteneri": -1}, "profit": 0},
            ],
        }
        sit["situatii"].append(noua)
        r = self.client.put("/api/admin/continut/situatii.json", json=sit, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["ok"])
        # motorul folosește conținutul nou
        self.assertEqual(self.client.get("/sanatate").json()["situatii"], len(sit["situatii"]))
        pe_disc = json.loads((TMP / "continut" / "situatii.json").read_text(encoding="utf-8"))
        self.assertEqual(pe_disc["situatii"][-1]["id"], "test-noua")

        # o legătură moartă e respinsă și nu se scrie
        sit["situatii"][-1]["optiuni"][0]["urmatoare"] = ["nu-exista"]
        r = self.client.put("/api/admin/continut/situatii.json", json=sit, headers=h)
        self.assertEqual(r.status_code, 422)
        self.assertIn("nu-exista", r.json()["detail"])
        pe_disc = json.loads((TMP / "continut" / "situatii.json").read_text(encoding="utf-8"))
        self.assertNotIn("nu-exista", json.dumps(pe_disc))

        r = self.client.get("/api/admin/verifica", headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertIn("avertismente", r.json())

        self.assertEqual(self.client.put("/api/admin/continut/altceva.json", json={}, headers=h).status_code, 404)

    def test_reseteaza_la_implicit(self):
        h = {"X-Parola": "secret"}
        niv = self.client.get("/api/admin/continut", headers=h).json()["niveluri.json"]
        niv["niveluri"][0]["nume"] = "Modificat"
        self.assertEqual(self.client.put("/api/admin/continut/niveluri.json", json=niv, headers=h).status_code, 200)
        self.assertEqual(self.client.get("/api/continut").json()["niveluri"][0]["nume"], "Modificat")
        r = self.client.post("/api/admin/reseteaza/niveluri.json", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotEqual(self.client.get("/api/continut").json()["niveluri"][0]["nume"], "Modificat")
        self.assertEqual(self.client.post("/api/admin/reseteaza/altceva.json", headers=h).status_code, 404)

    def test_sincronizare_cu_imaginea(self):
        """Fișierele needitate se actualizează; cele editate rămân."""
        import hashlib
        d = TMP / "continut"
        marker = json.loads((d / main.MARKER).read_text(encoding="utf-8")) if (d / main.MARKER).exists() else {}
        # fișier vechi dar needitat: diferit de imagine, cu hash-ul lui notat în marker
        (d / "arhetipuri.json").write_text('{"arhetipuri": []}', encoding="utf-8")
        marker["arhetipuri.json"] = hashlib.sha256(b'{"arhetipuri": []}').hexdigest()
        # fișier editat din admin: diferit și de imagine, și de marker
        (d / "carti.json").write_text('{"carti": []}', encoding="utf-8")
        marker["carti.json"] = "altceva"
        (d / main.MARKER).write_text(json.dumps(marker), encoding="utf-8")
        actualizate = main._seamana_continutul()
        self.assertIn("arhetipuri.json", actualizate)
        self.assertNotIn("carti.json", actualizate)
        self.assertEqual((d / "carti.json").read_text(encoding="utf-8"), '{"carti": []}')
        self.assertIn('"arhetipuri": [', (d / "arhetipuri.json").read_text(encoding="utf-8"))
        shutil.copy(RADACINA / "continut" / "carti.json", d / "carti.json")   # restaurăm pentru celelalte teste
        main.Stare.continut = None

    def test_actualizarea_automata_se_anuleaza_daca_nu_se_potriveste(self):
        """Niveluri noi (needitate) + situații editate care cer un nivel inexistent: nivelurile revin la ce erau."""
        import hashlib
        d = TMP / "continut"
        marker = json.loads((d / main.MARKER).read_text(encoding="utf-8"))
        # nivelurile din dataset: o versiune veche cu 10 niveluri, needitată (hash notat în marker)
        zece = {"niveluri": [{"nivel": i, "nume": f"N{i}", "prag": (i - 1) * 100} for i in range(1, 11)]}
        text_zece = json.dumps(zece)
        (d / "niveluri.json").write_text(text_zece, encoding="utf-8")
        marker["niveluri.json"] = hashlib.sha256(text_zece.encode("utf-8")).hexdigest()
        # situațiile: editate de admin, cer nivelul 10
        sit = json.loads((d / "situatii.json").read_text(encoding="utf-8"))
        sit["situatii"][0]["cerinte"] = {"nivel_min": 10}
        (d / "situatii.json").write_text(json.dumps(sit, ensure_ascii=False), encoding="utf-8")
        marker["situatii.json"] = "altceva"
        (d / main.MARKER).write_text(json.dumps(marker), encoding="utf-8")

        main.Stare.continut = None
        c = main.continut()   # nu trebuie să arunce
        self.assertEqual(len(c.niveluri), 10, "nivelurile au revenit la versiunea dinainte")
        self.assertEqual(json.loads((d / "niveluri.json").read_text(encoding="utf-8")), zece)
        # curățăm pentru celelalte teste
        for n in ("niveluri.json", "situatii.json"):
            shutil.copy(RADACINA / "continut" / n, d / n)
        main.Stare.continut = None

    def test_migrarea_continutului_vechi(self):
        from app import continut as mc
        brut = {
            "config.json": {"resurse": {"buget": {"nume": "Buget", "start": 40}, "bunastare": {"start": 50}, "legalitate": {"start": 50}},
                            "finaluri": {"buget": {"titlu": "Faliment"}}},
            "situatii.json": {"situatii": [{"optiuni": [{"ef": {"buget": -8, "legalitate": 2}, "profit": 10}, {"ef": {"buget": 4}}]}]},
            "carti.json": {"carti": [{"efect": {"buget": -2, "bunastare": 6, "scut": {"resurse": ["buget"]}}}]},
        }
        self.assertTrue(mc.migreaza(brut))
        self.assertEqual(brut["config.json"]["resurse"]["parteneri"]["start"], 40)
        self.assertNotIn("buget", brut["config.json"]["resurse"])
        self.assertIn("parteneri", brut["config.json"]["finaluri"])
        o1, o2 = brut["situatii.json"]["situatii"][0]["optiuni"]
        self.assertEqual(o1, {"ef": {"legalitate": 2}, "profit": 10 - 8 * mc.FACTOR_BUGET_IN_PROFIT})
        self.assertEqual(o2, {"profit": 4 * mc.FACTOR_BUGET_IN_PROFIT})
        self.assertEqual(brut["carti.json"]["carti"][0]["efect"], {"bunastare": 6, "profit": -2 * mc.FACTOR_BUGET_IN_PROFIT, "scut": {"resurse": ["parteneri"]}})
        self.assertFalse(mc.migreaza(brut), "a doua oară nu mai e nimic de migrat")

    def test_pagina_joc(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Patronache", r.text)

    def test_pagina_admin(self):
        r = self.client.get("/admin")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Patronache", r.text)


if __name__ == "__main__":
    unittest.main()
