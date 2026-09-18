# TraceX

An explainable cryptocurrency investigation platform for law-enforcement use.

Enter a victim-reported wallet address; get back a traced fund flow, related wallets,
detected laundering patterns, and a ranked list of **VASP candidates** — each one
carrying the evidence that produced it and an explicit confidence tier.

It does not tell you who owns a wallet. It tells you which regulated services the money
touched, on what evidence, so you know where to send legal process.

---

## Quick start

```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && cp .env.example .env
# add your free Etherscan key to .env, then:
python -m app.db.init_db && python -m app.db.seed_entities
uvicorn app.main:app --reload --port 8000

# frontend (second terminal)
cd frontend && npm install && npm run dev
```

Open <http://localhost:5173>. Windows instructions and the optional Docker stack are in
**[IMPLEMENTATION.md](IMPLEMENTATION.md)**.

No Postgres, Neo4j or Redis needed to start — SQLite and an in-process graph are the
defaults, and each service is a one-line config switch when you want it.

---

## Documentation

| | |
|---|---|
| **[IMPLEMENTATION.md](IMPLEMENTATION.md)** | Setup for Windows and Linux, first trace, production notes, troubleshooting |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | How the system works and why it is built this way |
| **[ml/MODEL_TRAINING.md](ml/MODEL_TRAINING.md)** | Training the risk model and verifying it in the app |
| **[ml/DATASET.md](ml/DATASET.md)** | Where to get training data, and what each dataset can teach |

---

## What it does

**Traces** a wallet 1–3 hops across Ethereum, Polygon or Bitcoin, normalising every
transaction to one chain-agnostic schema.

**Clusters** related addresses using chain-appropriate heuristics — deposit-address
detection on account-based chains, common-input-ownership on Bitcoin. These are separate
modules with no shared algorithms, because applying one chain's heuristics to another
produces confident nonsense.

**Detects** laundering patterns: fan-in/fan-out, consolidation, structuring near
thresholds, rapid pass-through layering, similar-value forwarding, mixer and bridge
interaction. Every hit cites its research basis.

**Generates VASP candidates** by combining known-address matches, cluster evidence, hop
distance and fund-flow volume — ranked, and never asserted as ownership.

**Scores risk** as a fusion of three separately-inspectable components: rule indicators
(0.45), threat intelligence (0.35) and a trained ML model (0.20). When no model is
trained, the ML weight is redistributed and the interface says so.

**Reports** the whole thing as a standardised PDF or JSON, including methodology and
limitations sections generated from the actual run.

---

## The design commitment

Nothing in this system outputs a conclusion without its basis. Every finding carries
evidence and one of four confidence tiers:

**Observed** (seen on-chain) · **Inferred** (derived by heuristic) ·
**Attributed** (matched to external intelligence) · **Confirmed** (verified ground truth)

This exists because of a measured fact. *Ghost Clusters* (USENIX Security '25) evaluated
the market-leading commercial attribution provider against ground truth from three seized
services: coverage ranged from ~25% to ~95%, misses were common, and coverage changed
over time. A system that presents attribution as settled fact misrepresents what it
knows — and an investigator who cannot explain where a claim came from cannot defend it.

---

## Stack

React + Vite · FastAPI · SQLAlchemy (SQLite or Postgres) · NetworkX (or Neo4j) ·
pandas · scikit-learn / XGBoost · ReportLab · Celery + Redis (optional)

Data sources: Etherscan API v2 (Ethereum and Polygon share one key) and Blockstream
Esplora for Bitcoin (free, keyless).

---

## Tests

```bash
cd backend && pytest tests/ -v
```

22 tests covering normalisation, graph construction, both clustering modules, the rule
engine, the VASP candidate engine, risk fusion and the shared feature contract —
including that CoinJoin transactions are excluded from Bitcoin clustering, and that
every pattern hit carries evidence and a research reference.

---

## Scope

TraceX identifies services that may hold identifying data; it does not identify people.
It detects mixer and bridge use rather than seeing through them. It does not follow
funds across a bridge automatically. It treats no output as proof — every candidate is
a lead requiring confirmation through lawful process.

Those limits are printed in every generated report, not buried here.
