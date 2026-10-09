# Patronache

Joc în care ești patronul unei firme românești, cinci ani. Motorul jocului,
API-ul, interfața jocului (la `/`) și meniul de admin pentru conținut (la `/admin`).

## Regulile (cum le implementează motorul)

- **Trei resurse**, 0..100: buget, bunăstare angajați, legalitate. Dacă una
  ajunge la 0, ai pierdut (faliment / toți au plecat / dosar penal).
- **5 ani × 4 trimestre × 2 decizii** (configurabil în `continut/config.json`).
- **Profit și nivel**: fiecare opțiune aduce profit (mii lei). La finalul
  anului profitul se adună la totalul firmei, iar totalul dă **nivelul 1..4**
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

- Jocul: http://127.0.0.1:8000/
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

## Instalare pe TrueNAS SCALE (24.10+, Docker nativ)

Imaginea e construită de GitHub Actions la fiecare push pe `main` și publicată
la `ghcr.io/stararcher5-droid/patronache:latest`, deci NAS-ul nu are nevoie de
git sau de build local.

1. Creează datasetul `/mnt/PollaSSD/apps/patronache/data` (Datasets → Add).
2. Apps → Discover Apps → Custom App → **Install via YAML**, lipește conținutul
   din `truenas-app.yaml` (verifică portul 9090 și calea datasetului).
3. Dacă vrei meniul de admin protejat, decomentează `PATRONACHE_ADMIN_PAROLA`
   și pune o parolă.
4. Jocul e la `http://IP-NAS:9090/`, admin-ul la `http://IP-NAS:9090/admin`.

Dacă NAS-ul nu poate trage imaginea (pachetul de pe ghcr.io e privat), rulează
o singură dată în shell-ul TrueNAS `docker login ghcr.io -u stararcher5-droid`
cu un token care are `read:packages`, sau fă pachetul public din GitHub:
Packages → patronache → Package settings → Change visibility.

**Update**: Apps → patronache → Stop, apoi Start; cu `pull_policy: always`
trage imaginea nouă. Datele și conținutul editat din admin rămân în dataset.

Alternativ, fără GitHub Actions, din shell-ul NAS:

```bash
git clone https://github.com/stararcher5-droid/patronache.git /mnt/PollaSSD/apps/patronache && cd /mnt/PollaSSD/apps/patronache && docker compose up -d --build
```

(în `docker-compose.yml` schimbă volumul `./data` în `/mnt/PollaSSD/apps/patronache/data`).

## Teste

```bash
python -m unittest discover -s tests
```
