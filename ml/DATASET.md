# DATASET.md

Where to get training data, what each dataset actually contains, and what it can and
cannot teach a model for this system.

Put everything you download in `ml/data/raw/`. That directory is gitignored — these
datasets range from tens of megabytes to a couple of gigabytes and several have licence
terms that make redistribution a bad idea.

---

## Quick comparison

| Dataset | Chain | Unit of analysis | Size | Labels | Best for |
|---|---|---|---|---|---|
| **Elliptic++ (actors)** | Bitcoin | wallet address | ~822k addresses | illicit / licit / unknown | The default. Wallet-level classification, which is what TraceX scores. |
| **Elliptic++ (transactions)** | Bitcoin | transaction | 203,769 tx | illicit / licit / unknown | Transaction-level work and GNN experiments |
| **BitcoinHeist** | Bitcoin | address-day | ~2.9M rows | ransomware family / white | Ransomware specifically; good feature-engineering reference |
| **Ethereum phishing** | Ethereum | account | varies | phishing / benign | The most relevant chain, but you assemble it yourself |
| **CryptoScamDB / Chainabuse** | multi | address | varies | reported-malicious | The *intelligence database*, not model training |

**Start with Elliptic++ actors.** It is the only large, public, labelled, wallet-level
graph dataset, and wallet-level is the granularity this system works at.

---

## 1. Elliptic++ — recommended starting point

**What it is:** an extension of the original Elliptic Bitcoin dataset that de-anonymised
99.5% of its transactions and added a wallet-address layer scraped from the Bitcoin
blockchain. It contains 203k transactions and 822k wallet addresses across 49 time steps
spaced roughly two weeks apart.

**Paper:** Elmougy, Y. and Liu, L. (2023), *Demystifying Fraudulent Transactions and
Illicit Nodes in the Bitcoin Network for Financial Forensics*, KDD '23.
arXiv: <https://arxiv.org/abs/2306.06108>

**Download:** <https://github.com/git-disl/EllipticPlusPlus>

The repo splits into a transactions dataset and an actors (wallet addresses) dataset.
**Download the actors dataset** — it is the one TraceX trains on.

```bash
cd ml/data/raw
git clone https://github.com/git-disl/EllipticPlusPlus.git
# then move the actors CSV(s) up into ml/data/raw/
```

The loader in `train_baseline.py` expects `wallets_features_classes_combined.csv`. If
the repo's filenames have changed since, point the loader at the actual file — it's a
single constant at the top of `load_elliptic()`.

**Labels:** class 1 = illicit, class 2 = licit, class 3 = unknown. The training script
drops class 3, because "unknown" genuinely means unknown — treating it as negative
would teach the model that unlabelled equals clean, which is the opposite of true in
this domain.

**The catch you need to know about:** roughly 2% of transactions are labelled illicit.
Accuracy is meaningless on this data — predicting "licit" for everything scores 98%.
The training script reports PR-AUC, precision and recall for the illicit class and
never optimises for accuracy. It also defaults to a **temporal** split, because the 49
time steps are chronological and a random split leaks the future into training.

---

## 2. BitcoinHeist — ransomware

**What it is:** Bitcoin addresses linked to ransomware families, with graph/topological
features derived from the transaction network (`length`, `weight`, `count`, `looped`,
`neighbors`, `income`).

**Paper:** Akcora, C. et al. (2019/2020), *BitcoinHeist: Topological Data Analysis for
Ransomware Prediction on the Bitcoin Blockchain*.

**Download:** UCI Machine Learning Repository, dataset 526
<https://archive.ics.uci.edu/dataset/526/bitcoinheistransomwareaddressdataset>

Extract `BitcoinHeistData.csv` into `ml/data/raw/`.

```bash
python src/train/train_baseline.py --dataset bitcoinheist --model xgboost
```

**Use it for:** a ransomware-specific model, and as a reference for feature engineering
— the topological features are a genuinely good idea and several are reflected in
TraceX's own feature schema.

**Don't use it for:** a general fraud model. It is ransomware-specific and heavily
time-bounded. Also note the `white` (non-ransomware) rows are *assumed* clean rather
than verified clean, so your negative class contains unknown contamination.

---

## 3. Ethereum phishing — most relevant, most work

Ethereum is the chain TraceX targets first, so an Ethereum-native model is the most
useful one you can have. There is no single canonical download; you assemble it.

### Step A — collect labelled addresses

**Positive class (phishing / scam / fraud):**

- **Etherscan's own label cloud** — Etherscan tags addresses with `phish-hack`.
  Browse <https://etherscan.io/labelcloud> and export the phish/hack label pages.
- **CryptoScamDB** — <https://cryptoscamdb.org>, open dataset of reported scam
  addresses and URLs. Has a public API.
- **Chainabuse** — <https://chainabuse.com>, community-reported abuse across chains.
  API access requires a key; check their terms for research use.
- **Published phishing-detection datasets** — the XBlock-ETH collection
  (<http://xblock.pro/#/dataset>) hosts the Ethereum phishing node/edge sets used by
  most of the GNN papers in this area, which makes your results comparable to the
  published literature.

**Negative class (benign):** harder, and the place most people get this wrong. Do not
just sample random addresses — you will pick up unlabelled scam addresses and teach the
model noise. Better: take addresses with substantial transaction history and no adverse
Etherscan tag, or use your own unit's verified-clean set. Aim for a ratio somewhere
between 1:5 and 1:20 positive:negative; more imbalanced than that and you should use
`--model xgboost`, which handles it through `scale_pos_weight`.

### Step B — build the feature table

Create `ml/data/raw/eth_labels.csv`:

```csv
address,label
0x00000000000000000000000000000000000dead1,1
0x00000000000000000000000000000000000cafe2,0
```

Then:

```bash
cd ml
python src/train/build_eth_dataset.py --labels data/raw/eth_labels.csv
```

This calls Etherscan once per address using **the backend's own ingestion and
normalisation code**, then computes features with **the same function the live
pipeline uses**. That means zero train/serve feature skew and 100% schema coverage —
which is why this path produces better models than the Bitcoin datasets, whose columns
have to be approximately mapped onto the schema.

It is rate-limited on purpose. A few thousand addresses on the free tier takes a while.
Start it and leave it running.

### Step C — train

```bash
python src/train/train_baseline.py --dataset eth-phishing --model xgboost --split random
```

Use `--split random` here (not temporal) unless your label file carries reliable
first-seen dates.

---

## 4. Intelligence feeds — different purpose

**CryptoScamDB** and **Chainabuse** appear twice in this document for a reason. As
*training data* they give you the positive class above. As *intelligence* they go into
a different place entirely: the Entity Intelligence Database, which the tracer checks
every traced address against.

Load them there via `backend/app/entity_intel/seed_data/known_addresses.json` (the file
documents its own schema) or through the **Entity intelligence** page in the UI.

The distinction matters: a model tells you a wallet *behaves* like a scam wallet; the
intelligence database tells you a specific address *was reported as* one. The first is
inference, the second is attribution, and TraceX reports them as different confidence
tiers on purpose.

---

## 5. Elliptic2 — for later graph work

If you move on to subgraph-level or GNN methods, Elliptic2 (Bellei et al., 2024)
provides 121,810 labelled subgraphs of Bitcoin clusters against a background graph of
49 million clusters and 196 million edges. That is the right dataset for money-laundering
*pattern* detection as opposed to node classification, and it pairs with the
PyTorch Geometric path described at the end of `MODEL_TRAINING.md`.

---

## Licences and handling

Check each source's terms before using it in anything operational:

- **Elliptic / Elliptic++** — research use; cite the KDD '23 paper.
- **BitcoinHeist (UCI)** — CC BY 4.0; cite the paper.
- **CryptoScamDB** — open data, check the repo licence.
- **Chainabuse** — terms of service apply; commercial and LEA use may need agreement.
- **Etherscan labels** — subject to Etherscan's terms; scraping at volume is restricted.

Two practical notes for law-enforcement use:

**Blockchain data is personal data in many jurisdictions.** Wallet addresses linked to
a complaint are case data. Treat `ml/data/raw/` and any dataset you build from live
traces with the same handling rules as the case file itself.

**Public labels are not evidence.** A CryptoScamDB report is a *report*. It belongs in
the intelligence database at confidence `attributed`, not `confirmed`, and TraceX's
report output preserves that distinction so it survives into court documents.
