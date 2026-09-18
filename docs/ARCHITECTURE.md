# Architecture

This document describes what TraceX does and why it is built this way. It follows the
plane structure of the system architecture diagram (Lucid: *Blockchain Fraud
Intelligence Platform — System Architecture*), and records the two or three places where
the implementation deliberately departs from it.

---

## The problem this solves

An investigator receives a complaint: a victim transferred cryptocurrency to an address
they were given. The investigator needs to know where the money went, and specifically
whether it reached a regulated service that can be served with legal process.

That last part is the whole game. A wallet address is not a person. The only realistic
route from an address to an identity runs through a VASP — an exchange, custodian or
similar regulated service — that holds KYC data and can be compelled to produce it. So
the practical question is not "who owns this wallet" but **"which VASPs did this money
touch, and how confident are we?"**

TraceX is built around that reframing.

---

## The design commitment

The system never outputs a bare attribution. Every result carries the evidence that
produced it and an explicit confidence tier:

| Tier | Meaning | Example |
|---|---|---|
| **Observed** | Directly visible on-chain | This transaction exists; these two addresses transacted |
| **Inferred** | Derived by a heuristic | These addresses share an owner (common-input); this wallet behaves like a deposit address |
| **Attributed** | Matched against external intelligence | This address is listed as belonging to Exchange X by *source, dated* |
| **Confirmed** | Verified ground truth | The exchange confirmed this address under legal process |

This is not decoration. Two things force it:

**A tiered claim survives cross-examination; a flat one does not.** "The system says
this is Exchange X" collapses under a defence question. "This address was swept to by a
cluster of 23 deposit addresses, and that destination is listed as Exchange X by a
source dated March 2026, which we have not independently confirmed" is a statement an
investigator can stand behind.

**The measured accuracy of attribution demands it.** Lubbertsen, van Eeten and van
Wegberg (*Ghost Clusters*, USENIX Security '25) evaluated the market-leading commercial
attribution provider against ground truth from three seized illicit services. Coverage
ranged from about 25% for a mixer to about 95% for a darknet marketplace — false
positives were rare (under 0.5%), but *misses were common*, and coverage changed over
time. If the best-resourced commercial product in the field has that profile, a system
that presents attribution as settled fact is misrepresenting what it knows. That paper's
caveat is embedded in the codebase and printed in every generated report.

---

## Planes

### Ingestion plane

One `ChainProvider` interface (`app/ingestion/base.py`); one adapter per chain; a
registry that maps a chain name to an adapter. Nothing downstream imports a specific
adapter.

| Chain | Adapter | Status |
|---|---|---|
| Ethereum | `evm_provider.py` (chainid 1) | Live |
| Polygon | `evm_provider.py` (chainid 137) | Live |
| Bitcoin | `bitcoin_provider.py` (Blockstream Esplora) | Live |
| TRON | `tron_provider.py` | Registered, not implemented |

Ethereum and Polygon share one adapter because since the August 2025 Etherscan API v2
migration they share one endpoint and one API key, distinguished only by a `chainid`
parameter. That keeps the integration surface to exactly two providers — Etherscan and
a Bitcoin indexer — while still supporting three chains.

TRON is registered but raises a clear `NotImplementedError` rather than silently
failing. It is not EVM-compatible and needs its own adapter; the brief scoped live
integrations to Etherscan and Bitcoin, so it stays a documented extension point.

### Normalization

Everything becomes one chain-agnostic row shape: `tx_hash, block_number, timestamp,
from, to, asset, value, fee, contract, method, direction, counterparty`. Deduplication
happens here (the EVM adapter merges `txlist` and `tokentx`, which overlap; the Bitcoin
adapter flattens UTXO sets into directed edges, which can repeat).

This is also where the light EDA lives — `to_dataframe()` is what the clustering,
pattern and feature code all consume, so there is one definition of "a transaction" in
the system.

### Graph engine

NetworkX `MultiDiGraph` in-process, with an optional Neo4j mirror.

The in-process graph is the default because it needs no installation and a single
trace's graph is small — hundreds of nodes, not millions. Neo4j earns its place when
you want the graph to *persist across cases*, so you can ask whether a cluster has
appeared before. That is a genuinely different capability, not a performance upgrade,
which is why it is a config switch rather than a requirement.

Hop expansion is capped per hop (`per_hop_cap` in the orchestrator). Without a cap, a
3-hop trace from a busy address becomes a full-chain crawl against a rate-limited free
API tier.

### Clustering — deliberately two modules

`evm_clustering.py` and `btc_clustering.py` share no algorithms, on purpose.

**EVM (account model)** — deposit-address detection, sweep-destination matching,
rapid pass-through detection. Grounded in Victor, F. (2020), *Address Clustering
Heuristics for Ethereum*: on account-based chains, exchange deposit addresses and their
forwarding behaviour are the dominant reliable clustering signal.

**Bitcoin (UTXO model)** — common-input-ownership, change-output inference,
consolidation detection. Grounded in the Meiklejohn et al. lineage.

The two models have no overlap. Common-input-ownership is meaningless on Ethereum;
deposit-sweep behaviour has no UTXO analogue. Applying one chain's heuristics to
another produces confident nonsense, which is the worst possible output for this system.

One detail worth calling out: the Bitcoin module **detects CoinJoin transactions and
excludes them from common-input clustering**, then flags them as mixer interaction
instead. CoinJoin exists specifically to make co-spending *not* imply shared ownership.
A clustering implementation that ignores this will merge unrelated people into one
cluster — and then confidently name them.

### Pattern engine

A rule engine over the normalized DataFrame, chain-agnostic. Detects fan-in/fan-out,
consolidation, structuring near thresholds, sudden large transfers, similar-value
forwarding, short-gap sequences, and mixer/bridge/DEX interaction.

Every hit carries `explanation`, `evidence` and `research_reference`. Most references
point at FATF (2020), *Virtual Assets Red Flag Indicators of Money Laundering and
Terrorist Financing* — which is the right anchor precisely because it is not academic:
it is what financial-intelligence units and regulated institutions already use, so a
report citing it speaks a language the recipient recognises.

Clustering findings are translated into the same `PatternHit` shape rather than
duplicated, so the API and UI deal with one unified list.

### Entity intelligence and threat intelligence

One table (`KnownEntity`) with `entity_type`, `source`, `source_date`, `evidence` and
`confidence`. Entity intelligence queries it for VASP-type entries; threat intelligence
queries it for scam/ransomware/mixer entries. One table, one seed format, one loader.

**It ships nearly empty, and that is a design decision.** The seed file contains only
unambiguous protocol constants (burn addresses). Populating it with plausible-looking
exchange address mappings would be actively harmful: an address marked `confirmed` that
is wrong sends a real investigation in the wrong direction. The file's own README block
points at the legitimate sources — CryptoScamDB, Chainabuse, licensed feeds, and your
own confirmed case attributions.

That last source is the one that compounds. The **Entity intelligence** page exists so
that when an exchange confirms an address under legal process, it goes back into the
database at confidence `confirmed`, with the response reference as its source. Closed
cases make the next case faster.

### VASP candidate engine

The core module. Inputs: the transaction DataFrame, the graph, known-entity matches,
and clustering output. Output: a ranked list of candidates, each with hop distance,
amount transferred, supporting transaction count, last interaction, supporting wallet
cluster, evidence lines, and a confidence tier.

Ranking is by confidence tier first, then evidence count, then hop proximity.

Two behaviours worth noting:

**Unattributed clusters are surfaced.** A destination with strong deposit-address
evidence but no name match appears as an `exchange_candidate` rather than being
dropped. Given the measured coverage gaps in attribution data, absence of a name match
is not evidence of absence of exchange-like behaviour — it usually just means the
intelligence database hasn't seen it.

**Nothing is ever asserted as ownership.** A candidate is a lead to verify. The report's
limitations section says so explicitly, as does the UI.

### Risk fusion

Three independently inspectable components:

| Component | Weight | Source |
|---|---|---|
| Rule indicators | 0.45 | The pattern engine, severity-weighted |
| Threat intelligence | 0.35 | Known scam/ransomware/mixer matches |
| ML behavioural score | 0.20 | The trained model, if one is loaded |

Rules carry the most weight because they are the component an investigator can defend
line by line. The ML score is a prioritisation aid, not the verdict — which is also why
a false positive from the model can only move the fused score so far.

When no model is trained, the ML weight is **redistributed** across the other two rather
than counted as a zero-risk vote, and the UI states plainly that the score is rule-based
only. An investigator should always be able to tell whether a number came from a trained
model or from rules.

### Cross-chain resolver

Phase 1 (implemented): detect interaction with a known bridge contract and surface it as
a cross-chain *exit* — evidence funds left the traced chain.

Phase 2 (documented extension point): decode per-bridge event logs to resolve the
destination chain and address, then feed that address back into the orchestrator to
continue the trace. This needs a protocol-by-protocol decoder and is scoped out of the
MVP, in line with the project's own roadmap.

### Reporting

PDF and JSON, with the same payload. The two sections most tools omit are generated
from the actual run rather than boilerplate:

- **Methodology** — which chains, which heuristics fired, whether an ML model was
  loaded, what the hop cap was.
- **Limitations** — what this trace cannot establish, including the attribution
  coverage caveat, the hop ceiling, the probabilistic nature of clustering, and the
  fact that identity, KYC, IP and beneficial-ownership data cannot come from on-chain
  data at all.

### Workers

Optional. With `REDIS_URL` unset, traces run in-process via FastAPI `BackgroundTasks`.
With it set, the same call dispatches to Celery.

The architecture diagram shows four worker types (ingestion, detection, enrichment,
report). The implementation runs the pipeline as one unit of work. Splitting it into
four separately-queued stages is right when trace volume justifies it — it is not right
for an MVP, where it would add four failure modes and a distributed-state problem in
exchange for nothing.

### AI copilot

Optional and strictly bounded. It sees only what the pipeline already produced — no
independent chain access — so it cannot introduce a fact that is not in the evidence
record. Its system prompt requires it to preserve the observed/inferred/attributed
distinction and forbids asserting ownership.

With `ANTHROPIC_API_KEY` unset, the copilot endpoints return a clear "not configured"
response and every other feature works normally. An investigation tool must not depend
on a language model to function.

---

## Where the implementation differs from the diagram

Three places, all deliberate:

1. **TRON is registered but not implemented.** It appears in the diagram's ingestion
   plane; it needs a non-EVM adapter, and the brief scoped live integrations to
   Etherscan and Bitcoin.
2. **Workers are one task, not four.** See above.
3. **Neo4j, Redis and Postgres are optional rather than assumed.** The diagram shows
   the production shape. The default configuration is the laptop shape — SQLite,
   in-process graph, inline execution — because a system that requires four services
   to start doesn't get run, and every one of those services is a single
   environment-variable switch away.

---

## Research foundations

| Area | Source |
|---|---|
| Ethereum address clustering, deposit-address behaviour | Victor, F. (2020), *Address Clustering Heuristics for Ethereum* |
| Attribution evaluation, coverage limits, the confidence-tier design | Lubbertsen, van Eeten & van Wegberg (2025), *Ghost Clusters*, USENIX Security '25 |
| Bitcoin wallet-level graph data and labels | Elmougy & Liu (2023), *Demystifying Fraudulent Transactions and Illicit Nodes in the Bitcoin Network*, KDD '23 (Elliptic++) |
| Ransomware features and topology | Akcora et al. (2019/2020), *BitcoinHeist* |
| Graph-based phishing detection (GNN roadmap) | Li, P. et al. (2022); TTAGN (WWW '22); TLMG4Eth (2025) |
| Red-flag indicators, the rule engine's basis | FATF (2020), *Virtual Assets Red Flag Indicators of ML/TF* |
| VASP ecosystem, regulatory context | FATF (2024), *Targeted Update on Implementation of the FATF Standards on VAs and VASPs* |

---

## What this system does not do

Stated plainly, because a tool used in criminal investigation should be explicit about
its limits:

- It does not identify people. It identifies services that may hold identifying data.
- It does not defeat mixers or privacy protocols. It detects that one was used and
  records that the trace ends there.
- It does not follow funds across a bridge automatically (Phase 2).
- It does not convert to fiat value. Amounts are in on-chain asset units at transaction
  time.
- It does not treat any output as proof. Every candidate is a lead requiring
  confirmation through lawful process.
