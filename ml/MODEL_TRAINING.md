# MODEL_TRAINING.md

How to train the wallet risk model and get it showing up in the application.

Dataset download links are in **[DATASET.md](DATASET.md)**. Read that first if you
haven't picked a dataset.

---

## The short version

```bash
cd tracex/ml
pip install -r requirements.txt

# 1. download a dataset into ml/data/raw/  (see DATASET.md)
# 2. train
python src/train/train_baseline.py --dataset elliptic --model random_forest

# 3. tell the running backend to pick it up
curl -X POST http://localhost:8000/api/ml/reload -H "Authorization: Bearer <token>"
```

Or click **Reload model** on the System status page. Confirm it worked: `/api/health`
flips `risk_model_loaded` to `true`, and the Risk panel in the workspace starts showing
an ML component with a non-zero weight.

---

## Setup

```bash
cd tracex/ml
pip install -r requirements.txt
```

If you already installed `backend/requirements.txt` in the same environment, most of
this is already there — `ml/requirements.txt` adds only the training extras.

Windows note: XGBoost sometimes needs the Visual C++ Redistributable. If the import
fails, install it from Microsoft, or train with `--model random_forest`, which has no
such dependency and performs comparably on these datasets.

---

## The one thing to understand before training

There is a single feature definition shared by training and serving:

```
ml/src/features/build_features.py  ->  extract_wallet_features()
```

It is imported by **both** `train_baseline.py` and the backend's
`app/risk/ml_inference.py`. That is deliberate. Training/serving feature skew — where
a feature means one thing during training and something subtly different in production
— is the most common way a deployed fraud model goes quietly wrong, and it is entirely
avoidable by having one definition.

The consequence: whatever dataset you train on has to be expressed in **this** schema.
The 20 features are wallet-behavioural, chain-agnostic and computed from transaction
history:

```
total_tx_count, in_count, out_count, in_out_ratio,
total_in_value, total_out_value, net_flow,
mean_value, std_value, max_value, max_value_share,
unique_counterparties, in_counterparty_count, out_counterparty_count,
counterparty_reuse_ratio, active_duration_days, tx_velocity_per_day,
mean_time_gap_seconds, std_time_gap_seconds, asset_diversity
```

Bitcoin datasets get *mapped* onto this schema (approximately — the script prints
exactly how much it covered and zero-fills the rest). An Ethereum set built with
`build_eth_dataset.py` is produced *in* this schema natively, at 100% coverage, which
is why it yields better models.

---

## Training options

```
--dataset   elliptic | bitcoinheist | eth-phishing
--model     random_forest | xgboost | logistic
--split     temporal | random
--test-frac 0.25
--raw-dir   ml/data/raw
--out       ml/models/wallet_risk_baseline.joblib
```

### Which model

| | When to use it |
|---|---|
| `random_forest` | **Start here.** No extra dependencies, handles imbalance via `class_weight`, gives feature importances the UI can display. |
| `xgboost` | Usually the best numbers. Uses `scale_pos_weight` for imbalance. Needs the `xgboost` package. |
| `logistic` | A baseline to beat. If your tree models don't clearly beat this, something is wrong with the features, not the model. |

### Which split

**`temporal` (default for Elliptic++ and BitcoinHeist).** These are time series. A
random split trains on the future and tests on the past, which produces a flattering
number that will not survive contact with a real case. The Elliptic++ literature
consistently shows performance degrading over time steps — a temporal split is what
exposes that honestly.

**`random`** only for datasets with no meaningful time ordering, such as an Ethereum
label set with no reliable first-seen dates.

---

## Reading the results

The script prints something like:

```
--- Held-out performance (illicit = positive class) ---
  pr_auc: 0.6412
  roc_auc: 0.9203
  precision_illicit: 0.7104
  recall_illicit: 0.5288
  f1_illicit: 0.6063
  confusion_matrix: {'tn': 10402, 'fp': 141, 'fn': 309, 'tp': 347}
```

**Look at PR-AUC, not accuracy, and not ROC-AUC.** With ~2% positives, ROC-AUC looks
impressive almost regardless of how useful the model is; PR-AUC is the honest number
for a heavily imbalanced problem.

**Then look at the trade-off you actually want.** In this application the model
*prioritises an investigator's queue*; it does not decide anything. That argues for
tuning toward recall — a missed illicit wallet is a lead that never gets looked at,
while a false positive costs an investigator a few minutes of reading evidence that
turns out to be thin. The risk fusion layer already limits the damage a false positive
can do by giving the ML score only 20% of the weight, with rules and threat
intelligence carrying the rest.

**A rough read on the output:**

- PR-AUC above ~0.6 on Elliptic++ with a temporal split: a reasonable model.
- PR-AUC around 0.3–0.5: usable for ranking, weak for anything else.
- PR-AUC below 0.3: the script warns you. It almost always means feature coverage is
  too sparse — check the coverage line near the top of the output.

Metrics are saved next to the model as `wallet_risk_baseline.metrics.json` and surfaced
in the UI on the System status page, so an investigator can see what they're relying on.

---

## Verifying it in the application

This is the step people skip, and then wonder why the score never changes.

1. **Backend health** — `GET /api/health` should show `"risk_model_loaded": true`.
2. **Model details** — `GET /api/ml/status` returns the algorithm, dataset, training
   date and held-out metrics.
3. **In the UI** — open **System status**. The risk-model card shows the algorithm,
   PR-AUC, precision, recall and training row count.
4. **In a trace** — open any completed investigation. The **Risk assessment** panel on
   the right lists three components. Before training, "ML behavioural model" reads
   *not trained yet* with weight 0.00 and the rule/threat weights are redistributed to
   compensate. After training, it shows the algorithm name, a score, and weight 0.20.

If step 4 still shows "not trained yet", the backend is looking somewhere else. Check
`RISK_MODEL_PATH` in `backend/.env` against the path printed at the end of training;
the default `../ml/models/wallet_risk_baseline.joblib` resolves relative to `backend/`.

---

## Retraining

Two triggers:

**New confirmed attributions.** Every case you close with a confirmed address is a new
labelled example. Periodically export your `confirmed` entities, add them to your
labels file, rebuild features and retrain. This is the loop that makes the system
improve with use rather than decay.

**Drift.** Laundering behaviour changes. The Elliptic++ results degrade across time
steps for exactly this reason, and the Ghost Clusters paper found commercial attribution
coverage also changes over time. Re-run training quarterly against recent data and
compare PR-AUC against the previous `metrics.json`. A meaningful drop means the
behavioural patterns have moved, not that the code broke.

---

## Where to go next: graph neural networks

The current model treats each wallet as an independent feature vector. That throws away
the graph — and the graph is where laundering structure actually lives. A wallet that
looks unremarkable alone can be obviously suspicious given its two-hop neighbourhood.

The natural progression, and the literature behind each step:

**1. GCN / GraphSAGE node classification.** Start here. Li, P. et al. (2022),
*Phishing Fraud Detection on Ethereum using Graph Neural Network* is the clean
reference implementation of the idea: accounts as nodes, transactions as edges, node
classification for phishing. GraphSAGE matters specifically because it is *inductive* —
it can score a wallet it never saw during training, which is a hard requirement here,
since every new case brings new addresses.

**2. Temporal GNNs.** Static graphs miss the sequencing that makes layering recognisable.
TTAGN (Li, S. et al., WWW '22) and GrabPhisher (Zhang et al., 2024) both attack this.
Time is not a nuisance dimension in this domain; the gap between receiving and forwarding
is itself the signal — it is why `rapid_receive_forward` is one of the rule engine's
highest-severity detectors.

**3. Transaction semantics + graph structure.** TLMG4Eth (2025) combines a transaction
language model with graph representation learning, which is currently among the stronger
published approaches for Ethereum fraud detection.

**4. Limited-label methods.** The real constraint in an LEA setting is not model
capacity, it is labels — you have very few confirmed illicit wallets and an enormous
unlabelled graph. Semi-supervised and contrastive approaches are the right family here,
and they align with how this system is meant to be used: ranking leads for an analyst,
not making autonomous determinations.

Practically:

```bash
pip install torch torch-geometric
```

The graph is already available in the shape PyG wants —
`backend/app/graph_engine/graph_service.py` builds a NetworkX `MultiDiGraph`, and
`torch_geometric.utils.from_networkx` converts it directly. Elliptic++ also ships
PyG-ready tutorial notebooks.

One caution worth keeping: a GNN makes the risk score harder to explain, and
explainability is not a nice-to-have in this system — it is the core requirement.
If you add one, add an attribution method alongside it (GNNExplainer, or attention
weights from a GAT) so the Risk panel can still show *why*. A score an investigator
cannot defend in court is not an improvement, however good its PR-AUC.

---

## Reference: full command list

```bash
# Bitcoin wallet-level, the default
python src/train/train_baseline.py --dataset elliptic --model random_forest
python src/train/train_baseline.py --dataset elliptic --model xgboost

# Ransomware-specific
python src/train/train_baseline.py --dataset bitcoinheist --model xgboost

# Ethereum, native schema — build the feature table first
python src/train/build_eth_dataset.py --labels data/raw/eth_labels.csv
python src/train/train_baseline.py --dataset eth-phishing --model xgboost --split random

# Baseline to beat
python src/train/train_baseline.py --dataset elliptic --model logistic
```
