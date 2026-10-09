# Patronache

Joc în care ești patronul unei firme românești, patru ani. Deocamdată doar
backendul (motorul jocului + API) și meniul de admin pentru conținut. Fără
interfață de joc încă.

## Regulile (cum le implementează motorul)

- **Trei resurse**, 0..100: buget, bunăstare angajați, legalitate. Dacă una
  ajunge la 0, ai pierdut (faliment / toți au plecat / dosar penal).
- **4 ani × 4 trimestre × 2 decizii** (configurabil în `continut/config.json`).
- **Profit și nivel**: fiecare opțiune aduce profit (mii lei). La finalul
  anului profitul se adună la totalul firmei, iar totalul dă **nivelul 1..10**
  (praguri în `continut/niveluri.json`). Un an pe minus poate coborî nivelul.
- **Nivelul deblochează alegeri**: o situație sau o singură opțiune poate cere
  `nivel_min` (ex. contractele cu ministerul doar la nivel 10). Opțiunile
  blocate se văd, dar cu motivul, și nu pot fi alese.
- **Situații legate**: o opțiune poate deschide alte situații (`urmatoare`),
  care vin la rând imediat; poate pune flaguri; o situație poate cere flaguri,
  cărți, nivel sau situații jucate înainte (`cerinte`). Situațiile marcate
  `doar_legata` nu apar la întâmplare. Ce nu e forțat de legături se trage la
  întâmplare dintre situațiile eligibile pe anul curent, ponderat cu `greutate`.
- **Cărți speciale** (petrecere cu pizza, team building, stand-up, concert):
  intră în inventar când alegi o opțiune care le dă; le folosești oricând în
  timpul unei decizii, se consumă și aplică efectul pe loc.
- **Rezultat**: nivelul atins, profitul total, cărțile, cum s-a terminat; dacă
  opțiunile au `teme`, și „cu ce tip de patron semeni” (arhetipuri).

## Pornire

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- Meniul de admin: http://127.0.0.1:8000/admin
- Documentația API: http://127.0.0.1:8000/docs

Variabile opționale: `PATRONACHE_DB` (calea bazei SQLite, implicit
`data/patronache.db`), `PATRONACHE_CONTINUT` (directorul cu JSON-uri),
`PATRONACHE_ADMIN_PAROLA` (dacă e setată, admin-ul cere parola).

## API-ul jocului

| Metodă | Cale | Ce face |
|---|---|---|
| POST | `/api/partida` | pornește o partidă `{nume, slogan, culoare, sigla}` → `{id, pas}` |
| GET | `/api/partida/{id}` | pasul curent |
| POST | `/api/partida/{id}/alege` | `{"optiune": 0..3}` → efect (delte, profit, carte primită, % jucători) + pasul următor |
| POST | `/api/partida/{id}/carte` | `{"carte": "<id>"}` folosește o carte din inventar |
| POST | `/api/partida/{id}/bilant` | închide anul → profit, nivel nou + pasul următor |
| GET | `/api/partida/{id}/rezultat` | rezultatul final (doar după final) |
| DELETE | `/api/partida/{id}` | renunță |
| GET | `/api/continut` | reguli, niveluri, cărți, arhetipuri |
| GET | `/api/statistici` | numere anonime |

`pas.pas` e unul din `decizie`, `bilant`, `final` (mandat dus la capăt sau nu
mai sunt situații), `terminat` (o resursă la 0). Efectele opțiunilor nu se
văd înainte de alegere.

## Conținutul

Totul e în `continut/*.json` și se editează din `/admin` (situații cu
legături, cerințe și opțiuni; cărți; niveluri; reguli; arhetipuri). Salvarea
validează tot conținutul împreună: o legătură către o situație inexistentă
sau o carte necunoscută e refuzată și nu se scrie nimic. Tab-ul „Verificare”
arată avertismente (prea puține situații pe un an, situații legate la care nu
ajunge nimeni, flaguri cerute pe care nu le pune nimeni).

Situațiile din repo sunt **exemple** de structură, nu conținutul final.

## Teste

```bash
python -m unittest discover -s tests
```
