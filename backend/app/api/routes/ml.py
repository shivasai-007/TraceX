"""Model status + hot reload, so training a new model doesn't need an API restart."""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_investigator
from app.db.models import Investigator
from app.risk.ml_inference import RiskModel

router = APIRouter(prefix="/api/ml", tags=["ml"])


@router.get("/status")
def status(investigator: Investigator = Depends(get_current_investigator)):
    model = RiskModel.instance()
    return {
        "available": model.available,
        "model_path": str(model._resolve_path()),
        "metadata": model.metadata,
        "feature_names": model.feature_names,
        "note": None if model.available else (
            "No trained model loaded. Risk scores are rule-based only until you train one "
            "(see ml/MODEL_TRAINING.md) and call POST /api/ml/reload."
        ),
    }


@router.post("/reload")
def reload_model(investigator: Investigator = Depends(get_current_investigator)):
    model = RiskModel.reload()
    return {
        "available": model.available,
        "metadata": model.metadata,
        "message": "Model reloaded." if model.available else "No model file found at the configured path.",
    }
