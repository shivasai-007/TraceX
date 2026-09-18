"""
ML Inference (architecture diagram: "ML Inference" -> "Risk Fusion").

Loads the artifact produced by ml/src/train/train_baseline.py and scores
a wallet from its normalized transaction rows.

Two properties this module guarantees, both deliberate:

1. IT USES THE SAME FEATURE CODE AS TRAINING. It imports
   extract_wallet_features from ml/src/features/build_features.py rather
   than re-implementing it. Training/serving feature skew is the most
   common silent failure mode in a deployed fraud model, and it is
   entirely avoidable.

2. IT DEGRADES GRACEFULLY. If no model file exists yet (i.e. before you
   have run the training script), the app does NOT crash and does NOT
   invent a score -- it returns available=False, and Risk Fusion falls
   back to the rule/heuristic score alone and says so in the UI. An
   investigator should always be able to see whether a number came from
   a trained model or from rules.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import joblib

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Make ml/src importable from the backend process. The ml/ directory is a
# sibling of backend/ in this repo; see docs/IMPLEMENTATION.md for the layout.
_ML_SRC = Path(__file__).resolve().parents[3] / "ml" / "src"
if str(_ML_SRC) not in sys.path:
    sys.path.insert(0, str(_ML_SRC))

try:
    from features.build_features import FEATURE_NAMES, extract_wallet_features  # type: ignore
except ImportError:  # pragma: no cover - only hit if ml/ was not checked out
    FEATURE_NAMES = []

    def extract_wallet_features(rows, focus_address):  # type: ignore
        return {}


class RiskModel:
    """Lazy-loading singleton wrapper around the trained artifact."""

    _instance: "RiskModel | None" = None

    def __init__(self):
        self.settings = get_settings()
        self.model = None
        self.metadata: dict = {}
        self.feature_names: list[str] = list(FEATURE_NAMES)
        self._load()

    @classmethod
    def instance(cls) -> "RiskModel":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reload(cls) -> "RiskModel":
        """Called by the /api/ml/reload endpoint after you train a new model,
        so you don't have to restart the API to pick it up."""
        cls._instance = cls()
        return cls._instance

    def _resolve_path(self) -> Path:
        raw = self.settings.risk_model_path
        p = Path(raw)
        if not p.is_absolute():
            # resolve relative to backend/ so the default "../ml/models/..." works
            p = (Path(__file__).resolve().parents[2] / raw).resolve()
        return p

    def _load(self) -> None:
        path = self._resolve_path()
        if not path.exists():
            logger.info("risk_model.not_found", path=str(path))
            return
        try:
            bundle = joblib.load(path)
            self.model = bundle["model"]
            self.metadata = bundle.get("metadata", {})
            self.feature_names = bundle.get("feature_names", self.feature_names)
            logger.info(
                "risk_model.loaded",
                path=str(path),
                algorithm=self.metadata.get("algorithm"),
                trained_at=self.metadata.get("trained_at"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("risk_model.load_failed", path=str(path), error=str(exc))
            self.model = None

    @property
    def available(self) -> bool:
        return self.model is not None

    def predict(self, rows: list[dict], focus_address: str) -> dict:
        if not self.available:
            return {
                "available": False,
                "score": None,
                "reason": (
                    "No trained risk model found. Train one with ml/src/train/train_baseline.py "
                    "(see ml/MODEL_TRAINING.md), then call POST /api/ml/reload. Until then the "
                    "risk score shown is rule-based only."
                ),
            }

        features = extract_wallet_features(rows, focus_address)
        vector = [[float(features.get(name, 0.0)) for name in self.feature_names]]
        try:
            proba = float(self.model.predict_proba(vector)[0][1])
        except Exception as exc:  # noqa: BLE001
            logger.warning("risk_model.predict_failed", error=str(exc))
            return {"available": False, "score": None, "reason": f"Model inference failed: {exc}"}

        return {
            "available": True,
            "score": round(proba, 4),
            "algorithm": self.metadata.get("algorithm"),
            "trained_at": self.metadata.get("trained_at"),
            "training_dataset": self.metadata.get("dataset"),
            "validation_metrics": self.metadata.get("metrics"),
            "top_features": self._explain(features),
            "features_used": features,
        }

    def _explain(self, features: dict, top_n: int = 5) -> list[dict]:
        """Global feature importances from the trained model, paired with this
        wallet's actual values. Not a per-prediction attribution (use SHAP for
        that -- see ml/MODEL_TRAINING.md), but enough for an investigator to
        see which behaviors the model weighs and what this wallet showed."""
        importances = getattr(self.model, "feature_importances_", None)
        if importances is None:
            return []
        paired = sorted(
            zip(self.feature_names, importances), key=lambda kv: kv[1], reverse=True
        )[:top_n]
        return [
            {
                "feature": name,
                "importance": round(float(imp), 4),
                "wallet_value": round(float(features.get(name, 0.0)), 6),
            }
            for name, imp in paired
        ]
