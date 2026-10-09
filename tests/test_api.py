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
        self.assertEqual(set(d["resurse"]), {"buget", "bunastare", "legalitate"})
        self.assertEqual(len(d["niveluri"]), 4)
        self.assertTrue(all("efect" in c for c in d["carti"]), "jucătorul vede ce face o carte")

    def test_partida_prin_http(self):
        r = self.client.post("/api/partida", json={"nume": "Test SRL", "slogan": "merge"})
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
                {"text": "da", "ef": {"buget": 1}, "profit": 5, "urmatoare": [sit["situatii"][0]["id"]]},
                {"text": "nu", "ef": {"buget": -1}, "profit": 0},
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
