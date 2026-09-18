"""
Train the wallet risk model.

    python src/train/train_baseline.py --dataset elliptic --model xgboost

Produces ml/models/wallet_risk_baseline.joblib, which the backend loads
automatically (see backend/app/risk/ml_inference.py). Full instructions,
including where to download each dataset, are in ml/MODEL_TRAINING.md
and ml/DATASET.md.

Design notes worth knowing before you train:

* CLASS IMBALANCE IS THE WHOLE PROBLEM. Illicit wallets are ~2% of
  Elliptic++. Accuracy is a useless metric here -- a model that predicts
  "licit" for everything scores 98%. This script reports PR-AUC,
  precision, recall and F1 for the illicit class, and never optimizes for
  accuracy.

* TEMPORAL SPLITS, NOT RANDOM ONES. Elliptic++ and BitcoinHeist are time
  series (49 time steps / block-dated rows). A random split leaks the
  future into the training set and produces a flattering, wrong number.
  --split temporal is the default for those datasets.

* THE FEATURE SCHEMA IS SHARED WITH SERVING. Dataset-native features are
  mapped onto the same FEATURE_NAMES that the live pipeline computes from
  a wallet's transactions. Anything the dataset can't supply is filled
  with 0.0 and reported, so you can see exactly how much of the schema a
  given dataset actually covers.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.build_features import FEATURE_NAMES  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------- loaders

def load_elliptic(raw_dir: Path) -> tuple[pd.DataFrame, pd.Series, pd.Series, dict]:
    """Elliptic++ ACTORS (wallet-address) dataset.

    We train on the actors table, not the transactions table, because
    TraceX scores WALLETS -- that is what an investigator submits. Labels:
    1 = illicit, 2 = licit, 3 = unknown (dropped; this is supervised
    training, and 'unknown' is genuinely unknown, not negative).
    """
    features_path = raw_dir / "wallets_features_classes_combined.csv"
    if not features_path.exists():
        raise FileNotFoundError(
            f"Expected {features_path}.\n"
            "Download the Elliptic++ actors dataset -- see ml/DATASET.md, section 'Elliptic++'."
        )
    df = pd.read_csv(features_path)

    label_col = next((c for c in ("class", "Class", "label") if c in df.columns), None)
    if label_col is None:
        raise ValueError(f"No label column found in {features_path}. Columns: {list(df.columns)[:15]}")

    df = df[df[label_col].isin([1, 2, "1", "2"])].copy()
    y = (df[label_col].astype(str) == "1").astype(int)  # 1 = illicit = positive class

    time_col = next((c for c in ("Time step", "time_step", "timestep") if c in df.columns), None)
    time_index = df[time_col] if time_col else pd.Series(range(len(df)), index=df.index)

    drop_cols = {label_col, time_col, "address", "Address"} - {None}
    X_native = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore")
    X_native = X_native.select_dtypes(include=[np.number]).fillna(0.0)

    X, coverage = _map_to_feature_schema(X_native, ELLIPTIC_COLUMN_MAP)
    return X, y, time_index, coverage


def load_bitcoinheist(raw_dir: Path) -> tuple[pd.DataFrame, pd.Series, pd.Series, dict]:
    """BitcoinHeist ransomware dataset (UCI).

    Label: the 'label' column is 'white' for non-ransomware, or a
    ransomware family name otherwise. Positive class = any ransomware family.
    """
    path = raw_dir / "BitcoinHeistData.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Expected {path}.\nDownload it -- see ml/DATASET.md, section 'BitcoinHeist'."
        )
    df = pd.read_csv(path)
    y = (df["label"].astype(str).str.lower() != "white").astype(int)
    time_index = df["year"] * 1000 + df["day"] if {"year", "day"}.issubset(df.columns) else pd.Series(range(len(df)))

    X_native = df.drop(columns=["label", "address"], errors="ignore").select_dtypes(include=[np.number]).fillna(0.0)
    X, coverage = _map_to_feature_schema(X_native, BITCOINHEIST_COLUMN_MAP)
    return X, y, time_index, coverage


def load_eth_phishing(raw_dir: Path) -> tuple[pd.DataFrame, pd.Series, pd.Series, dict]:
    """Ethereum phishing account dataset in TraceX's own schema.

    This is the loader to use when you've built a training set from real
    Ethereum transactions using ml/src/train/build_eth_dataset.py -- that
    script emits exactly FEATURE_NAMES plus 'label' and 'address', so no
    column mapping is needed and feature coverage is 100%.
    """
    path = raw_dir / "eth_wallet_features.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Expected {path}.\n"
            "Build it with: python src/train/build_eth_dataset.py --labels data/raw/eth_labels.csv\n"
            "See ml/DATASET.md, section 'Ethereum phishing'."
        )
    df = pd.read_csv(path)
    y = df["label"].astype(int)
    time_index = pd.Series(range(len(df)))
    X = df.reindex(columns=FEATURE_NAMES).fillna(0.0)
    coverage = {"mapped": len(FEATURE_NAMES), "total": len(FEATURE_NAMES), "unmapped": []}
    return X, y, time_index, coverage


# ------------------------------------------------- dataset -> schema maps
# Maps a dataset's native column onto TraceX's serving feature schema, so a
# model trained on public data can score a live wallet. Columns with no
# honest equivalent are left out rather than force-fitted.

ELLIPTIC_COLUMN_MAP = {
    "total_txs": "total_tx_count",
    "num_txs_as_sender": "out_count",
    "num_txs_as_receiver": "in_count",
    "btc_transacted_total": "total_in_value",
    "btc_sent_total": "total_out_value",
    "btc_transacted_mean": "mean_value",
    "btc_transacted_max": "max_value",
    "num_addr_transacted_multiple": "counterparty_reuse_ratio",
    "lifetime_in_blocks": "active_duration_days",
    "transacted_w_address_total": "unique_counterparties",
}

BITCOINHEIST_COLUMN_MAP = {
    "length": "total_tx_count",
    "count": "out_count",
    "neighbors": "unique_counterparties",
    "income": "total_in_value",
    "weight": "max_value_share",
    "looped": "counterparty_reuse_ratio",
}


def _map_to_feature_schema(X_native: pd.DataFrame, column_map: dict) -> tuple[pd.DataFrame, dict]:
    out = pd.DataFrame(0.0, index=X_native.index, columns=FEATURE_NAMES)
    mapped = []
    for native_col, schema_col in column_map.items():
        if native_col in X_native.columns and schema_col in out.columns:
            out[schema_col] = X_native[native_col].astype(float)
            mapped.append(schema_col)
    unmapped = [c for c in FEATURE_NAMES if c not in mapped]
    coverage = {"mapped": len(mapped), "total": len(FEATURE_NAMES), "unmapped": unmapped}
    return out, coverage


LOADERS = {
    "elliptic": load_elliptic,
    "bitcoinheist": load_bitcoinheist,
    "eth-phishing": load_eth_phishing,
}


# ---------------------------------------------------------------- models

def build_model(name: str, scale_pos_weight: float):
    if name == "xgboost":
        try:
            from xgboost import XGBClassifier
        except ImportError as exc:
            raise SystemExit(
                "xgboost is not installed. Run: pip install xgboost\n"
                "Or train with --model random_forest / --model logistic instead."
            ) from exc
        return XGBClassifier(
            n_estimators=400,
            max_depth=6,
            learning_rate=0.08,
            subsample=0.9,
            colsample_bytree=0.9,
            scale_pos_weight=scale_pos_weight,  # handles the ~50:1 class imbalance
            eval_metric="aucpr",
            tree_method="hist",
            n_jobs=-1,
            random_state=42,
        )
    if name == "random_forest":
        return RandomForestClassifier(
            n_estimators=400,
            max_depth=None,
            min_samples_leaf=2,
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=42,
        )
    if name == "logistic":
        return Pipeline([
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42)),
        ])
    raise ValueError(f"Unknown model: {name}")


def split(X: pd.DataFrame, y: pd.Series, time_index: pd.Series, mode: str, test_frac: float):
    if mode == "temporal":
        order = np.argsort(time_index.values, kind="stable")
        cut = int(len(order) * (1 - test_frac))
        train_idx, test_idx = order[:cut], order[cut:]
        return X.iloc[train_idx], X.iloc[test_idx], y.iloc[train_idx], y.iloc[test_idx]
    from sklearn.model_selection import train_test_split

    return train_test_split(X, y, test_size=test_frac, stratify=y, random_state=42)


def evaluate(model, X_test, y_test) -> dict:
    proba = model.predict_proba(X_test)[:, 1]
    preds = (proba >= 0.5).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_test, preds, average="binary", zero_division=0
    )
    tn, fp, fn, tp = confusion_matrix(y_test, preds, labels=[0, 1]).ravel()
    return {
        "pr_auc": round(float(average_precision_score(y_test, proba)), 4),
        "roc_auc": round(float(roc_auc_score(y_test, proba)), 4),
        "precision_illicit": round(float(precision), 4),
        "recall_illicit": round(float(recall), 4),
        "f1_illicit": round(float(f1), 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "test_size": int(len(y_test)),
        "test_positive_rate": round(float(y_test.mean()), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the TraceX wallet risk model.")
    parser.add_argument("--dataset", choices=list(LOADERS), default="elliptic")
    parser.add_argument("--model", choices=["xgboost", "random_forest", "logistic"], default="random_forest")
    parser.add_argument("--split", choices=["temporal", "random"], default="temporal")
    parser.add_argument("--test-frac", type=float, default=0.25)
    parser.add_argument("--raw-dir", type=Path, default=DATA_DIR / "raw")
    parser.add_argument("--out", type=Path, default=MODEL_DIR / "wallet_risk_baseline.joblib")
    args = parser.parse_args()

    print(f"Loading dataset: {args.dataset}")
    X, y, time_index, coverage = LOADERS[args.dataset](args.raw_dir)
    print(f"  rows: {len(X):,}   positive (illicit): {int(y.sum()):,} ({y.mean():.2%})")
    print(f"  feature schema coverage: {coverage['mapped']}/{coverage['total']}")
    if coverage["unmapped"]:
        print(f"  not supplied by this dataset (zero-filled): {', '.join(coverage['unmapped'][:8])}"
              f"{' ...' if len(coverage['unmapped']) > 8 else ''}")

    X_train, X_test, y_train, y_test = split(X, y, time_index, args.split, args.test_frac)
    print(f"Split ({args.split}): train {len(X_train):,} / test {len(X_test):,}")

    pos = max(int(y_train.sum()), 1)
    scale_pos_weight = (len(y_train) - pos) / pos
    print(f"Training {args.model} (scale_pos_weight={scale_pos_weight:.1f})...")
    model = build_model(args.model, scale_pos_weight)
    model.fit(X_train, y_train)

    metrics = evaluate(model, X_test, y_test)
    print("\n--- Held-out performance (illicit = positive class) ---")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    print("\n" + classification_report(y_test, model.predict(X_test), zero_division=0,
                                       target_names=["licit", "illicit"]))

    if metrics["pr_auc"] < 0.3:
        print("WARNING: PR-AUC is low. With a heavily imbalanced dataset this usually means the")
        print("         feature mapping is too sparse. Check the coverage line above, and consider")
        print("         building a native-schema training set with build_eth_dataset.py instead.")

    bundle = {
        "model": model,
        "feature_names": FEATURE_NAMES,
        "metadata": {
            "algorithm": args.model,
            "dataset": args.dataset,
            "split": args.split,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
            "feature_coverage": coverage,
            "training_rows": int(len(X_train)),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, args.out)
    print(f"\nSaved model -> {args.out}")

    report_path = args.out.with_suffix(".metrics.json")
    report_path.write_text(json.dumps(bundle["metadata"], indent=2))
    print(f"Saved metrics -> {report_path}")
    print("\nNext: start the backend and call POST /api/ml/reload (or restart it) to pick this up.")
    print("Verify with GET /api/ml/status -- it should report available: true.")


if __name__ == "__main__":
    main()
