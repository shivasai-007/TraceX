# IMPLEMENTATION.md

How to run TraceX on Windows or Linux. Follow this top to bottom the first time.

Everything here works with **no Docker, no Postgres, no Neo4j and no Redis** — those
are optional upgrades covered at the end. The default setup uses a local SQLite file
and an in-process graph, which is enough to run real traces against live blockchain data.

---

## 0. What you need

| | Version | Check with | Notes |
|---|---|---|---|
| Python | 3.11 or 3.12 | `python --version` | 3.13 works but some ML wheels lag behind |
| Node.js | 18+ | `node --version` | 20 LTS recommended |
| Etherscan API key | free tier | — | Only needed for Ethereum/Polygon. Bitcoin needs no key. |

Get the Etherscan key at <https://etherscan.io/apidashboard>. One key covers Ethereum
*and* Polygon — since the August 2025 API v2 migration, Etherscan serves 60+ EVM chains
from one endpoint with a `chainid` parameter, which is why this project needs only one
EVM integration rather than one per chain.

---

## 1. Get the code and set up the backend

### Linux / macOS

```bash
cd tracex/backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

### Windows (PowerShell)

```powershell
cd tracex\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

> If PowerShell blocks the activate script, run
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first — that only
> affects the current window.

### Windows (Command Prompt)

```cmd
cd tracex\backend
python -m venv .venv
.venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

---

## 2. Configure

Open `backend/.env` and set two things:

```ini
SECRET_KEY=<paste a long random string here>
ETHERSCAN_API_KEY=<your free key>
```

Generate a secret key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Leave everything else at its default for now. Each setting is documented inline in
`.env.example`, including what turning it on actually changes.

---

## 3. Create the database

From `backend/`, with the virtualenv active:

```bash
python -m app.db.init_db
python -m app.db.seed_entities
```

The first command creates the tables and a starter account:

```
admin@tracex.local  /  ChangeMe123!
```

**Change that password.** Sign in, then create your own account through the UI's
"Create an investigator account" link and deactivate the demo one.

The second command loads `backend/app/entity_intel/seed_data/known_addresses.json`
into the intelligence database. It ships nearly empty on purpose — see
[§8 Populating the intelligence database](#8-populating-the-intelligence-database).

---

## 4. Start the backend

```bash
uvicorn app.main:app --reload --port 8000
```

Check it:

- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/api/health>

The health endpoint tells you exactly what is wired up:

```json
{
  "status": "ok",
  "chains_live": ["ethereum", "polygon", "bitcoin"],
  "etherscan_key_configured": true,
  "graph_backend": "networkx",
  "workers_enabled": false,
  "copilot_enabled": false,
  "risk_model_loaded": false
}
```

`risk_model_loaded: false` is expected until you train a model (step 6).

---

## 5. Start the frontend

In a **second terminal**:

```bash
cd tracex/frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The Vite dev server proxies `/api` to
`http://localhost:8000`, so no CORS configuration is needed in development.

At this point you can sign in, open a case, and run a real trace.

---

## 6. Train the risk model

The app runs fine without it — risk is scored from rules and threat intelligence, and
the UI says so plainly rather than hiding the gap. But the ML component is part of the
design, so train it once you have the app running.

Full instructions: **[`ml/MODEL_TRAINING.md`](ml/MODEL_TRAINING.md)**
Dataset download links and licence notes: **[`ml/DATASET.md`](ml/DATASET.md)**

Short version:

```bash
cd tracex/ml
pip install -r requirements.txt
# download a dataset into ml/data/raw/ (see ml/DATASET.md)
python src/train/train_baseline.py --dataset elliptic --model random_forest
```

Then either restart the backend or, without restarting, call:

```bash
curl -X POST http://localhost:8000/api/ml/reload -H "Authorization: Bearer <your-token>"
```

You can also click **Reload model** on the System status page in the UI. Confirm it
worked: `risk_model_loaded` flips to `true` on `/api/health`, and the Risk panel in the
workspace starts showing an ML component with a non-zero weight.

---

## 7. Run your first trace

1. Sign in.
2. **Cases → New case.** Give it your unit's real case number and the complaint text.
3. On the case page, enter the wallet address the victim reported, pick the chain, and
   choose a trace depth.
   - **1 hop** — direct counterparties only. Fast, few API calls.
   - **2 hops** — the default. Usually enough to reach a deposit address.
   - **3 hops** — deepest. Many more API calls; on the free Etherscan tier this can
     take several minutes.
4. The page redirects to the workspace and polls until the trace completes.
5. Read the tabs: **Fund flow** (interactive graph), **VASP candidates** (each with its
   evidence), **Patterns** (each with its research basis), **Timeline**.
6. **Download report** produces the standardised PDF, including the methodology and
   limitations sections.

If a trace fails, the workspace shows the reason. The usual causes are a missing or
rate-limited API key, or an address that doesn't exist on the chain you selected.

---

## 8. Populating the intelligence database

This is the single highest-leverage thing you can do to improve results, and it is
worth understanding why.

The VASP candidate engine combines *behavioural* evidence (deposit-address sweeps,
common-input clusters, fund-flow shape) with *known-address* evidence. The behavioural
half works out of the box. The known-address half is only as good as what you load in.

Three ways to fill it, in increasing order of value:

1. **Public scam/abuse feeds.** CryptoScamDB and Chainabuse publish reported malicious
   addresses. These give you the `scam` and `ransomware` entity types, which drive the
   threat-intelligence component of the risk score.
2. **A licensed intelligence feed.** If your unit already subscribes to a commercial
   provider, their labels map directly onto the `source` / `source_date` /
   `confidence` fields — those fields exist precisely to record provenance.
3. **Your own confirmed attributions.** When an exchange confirms an address through
   legal process, record it on the **Entity intelligence** page with confidence
   `confirmed` and the response reference as the source. This is how a closed case
   makes the next one faster, and it is the only source of genuine ground truth you
   will have.

The shipped seed file deliberately contains only unambiguous protocol constants (burn
addresses) rather than guessed exchange mappings. A wrong address-to-entity mapping
marked `confirmed` can send a real investigation in the wrong direction, so the file
contains a README block explaining this and pointing at the sources above.

---

## 9. Optional: the full stack with Docker

Brings up Postgres, Neo4j and Redis alongside the API, matching the production-shaped
architecture rather than the laptop-shaped one.

```bash
cd tracex
docker compose up -d
```

Then in `backend/.env`:

```ini
DATABASE_URL=postgresql+psycopg2://tracex:tracex@localhost:5432/tracex
GRAPH_BACKEND=neo4j
NEO4J_PASSWORD=tracex-dev-password
REDIS_URL=redis://localhost:6379/0
```

Re-run `python -m app.db.init_db` to create the tables in Postgres, then restart the API.

**What each service adds:**

| Service | What changes |
|---|---|
| Postgres | Durable case storage suitable for more than one investigator |
| Neo4j | The fund-flow graph persists across restarts, and you can ask cross-case questions ("has this cluster appeared before?"). Browser at <http://localhost:7474> |
| Redis | Traces move to background workers, so a 3-hop trace doesn't occupy an API process |

With Redis configured, start a worker:

```bash
# Linux / macOS
celery -A app.workers.celery_app worker --loglevel=info

# Windows — the default worker pool doesn't work there, so use solo
celery -A app.workers.celery_app worker --loglevel=info --pool=solo
```

---

## 10. Building for production

```bash
cd frontend
npm run build          # outputs to frontend/dist/
```

Serve `frontend/dist/` from any static host, and run the API behind a real server:

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Before deploying anywhere real:

- Set `ENVIRONMENT=production` and a strong `SECRET_KEY`.
- Set `FRONTEND_ORIGIN` to your actual frontend URL (CORS).
- Move off SQLite to Postgres.
- Put TLS in front of the API. Case data and wallet addresses are sensitive.
- Replace `create_all()` with Alembic migrations once the schema stops changing:
  `alembic init alembic`, point `sqlalchemy.url` at your `DATABASE_URL`, then
  `alembic revision --autogenerate -m "initial"`.

---

## Cross-platform notes

Both platforms are supported, and these are the only places they differ:

| | Linux / macOS | Windows |
|---|---|---|
| Activate venv | `source .venv/bin/activate` | `.\.venv\Scripts\Activate.ps1` |
| Copy a file | `cp` | `copy` |
| Path separator in `.env` | `/` | `/` also works — Python normalises it |
| Celery worker | default pool | add `--pool=solo` |
| Long paths | fine | enable long path support if `npm install` fails deep in `node_modules` |

The code itself uses `pathlib` throughout and never hardcodes a path separator, so no
source changes are needed between platforms.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'app'`**
You're not in `backend/`. All backend commands run from that directory.

**`You are using a deprecated V1 endpoint`**
Your Etherscan key is fine, but something is calling the old API. This project uses v2
throughout — if you see this, you've modified `app/ingestion/evm_provider.py`.

**Trace returns no transactions**
Check the address exists on the chain you selected. An Ethereum address is valid
*syntax* on Polygon but will usually have no history there.

**Rate limited during a 3-hop trace**
The free Etherscan tier allows 5 calls/second and caps list endpoints at 1,000 records
per request. Drop to 2 hops, or add a paid key. The per-hop expansion caps in
`app/orchestrator/case_orchestrator.py` (`per_hop_cap`) exist for this reason and can
be lowered further.

**`npm install` fails on Windows with a path-length error**
Enable long paths: `git config --system core.longpaths true`, or move the project
closer to the drive root.

**The PDF downloads as a broken file**
Report downloads go through `fetch` with the auth header rather than a plain link, so a
broken file usually means the trace isn't `complete`. The API returns 409 with an
explanation in that case.

---

## Where things live

```
tracex/
├── backend/
│   └── app/
│       ├── core/            config, auth, logging
│       ├── db/              models, session, init + seed scripts
│       ├── ingestion/       chain adapters + provider registry
│       ├── normalization/   raw tx -> chain-agnostic schema, EDA
│       ├── graph_engine/    NetworkX graph + optional Neo4j mirror
│       ├── clustering/      evm_clustering.py, btc_clustering.py (deliberately separate)
│       ├── patterns/        the rule engine
│       ├── entity_intel/    known-address database + seed data
│       ├── threat_intel/    scam/ransomware exposure
│       ├── attribution/     VASP candidate + evidence engine
│       ├── cross_chain/     bridge exit detection
│       ├── risk/            ML inference + risk fusion
│       ├── orchestrator/    the pipeline, in order, in one file
│       ├── reporting/       PDF + JSON report builder
│       ├── copilot/         optional AI summaries
│       ├── workers/         optional Celery tasks
│       └── api/routes/      FastAPI endpoints
├── frontend/src/
│   ├── theme/               design tokens + light/dark provider
│   ├── components/          graph canvas, evidence components
│   ├── pages/               login, cases, case detail, workspace, entities, status
│   └── api/client.js
├── ml/
│   ├── src/features/        THE shared feature contract (training + serving)
│   ├── src/train/           training scripts
│   ├── data/raw/            put downloaded datasets here
│   ├── models/              trained artifacts land here
│   ├── MODEL_TRAINING.md
│   └── DATASET.md
└── docs/ARCHITECTURE.md
```
