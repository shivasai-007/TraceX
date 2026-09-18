from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Chain = Literal["ethereum", "polygon", "bitcoin", "tron"]


class WalletInvestigateRequest(BaseModel):
    address: str = Field(..., description="Wallet address to investigate")
    chain: Chain
    seed_tx_hash: str | None = None
    max_hops: int = Field(2, ge=1, le=3, description="1-3 hop graph traversal, per the MVP scope")


class WalletInvestigationOut(BaseModel):
    id: str
    case_id: str
    address: str
    chain: str
    status: str
    summary: dict | None = None
    risk_result: dict | None = None
    patterns: dict | None = None
    vasp_candidates: dict | None = None
    timeline: dict | None = None
    cross_chain: dict | None = None
    copilot_summary: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}
