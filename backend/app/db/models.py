"""
Relational schema (PostgreSQL in production, SQLite for local dev).

This deliberately holds *case-management and intelligence* data -- the
things you query relationally (who owns which case, what a wallet's last
computed risk score was, which entities are known). The raw fund-flow
graph itself lives in the graph store (Neo4j / NetworkX), not here --
see app/graph_engine.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class CaseStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING_REVIEW = "pending_review"
    CLOSED = "closed"


class Chain(str, enum.Enum):
    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    BITCOIN = "bitcoin"
    TRON = "tron"  # registered, not yet implemented -- see ingestion/tron_provider.py


class Investigator(Base):
    __tablename__ = "investigators"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    badge_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    cases: Mapped[list["Case"]] = relationship(back_populates="lead_investigator")


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    crime_type: Mapped[str] = mapped_column(String(128))
    victim_complaint: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CaseStatus] = mapped_column(Enum(CaseStatus), default=CaseStatus.OPEN)
    lead_investigator_id: Mapped[str] = mapped_column(ForeignKey("investigators.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    lead_investigator: Mapped["Investigator"] = relationship(back_populates="cases")
    wallets: Mapped[list["WalletInvestigation"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    notes: Mapped[list["CaseNote"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class WalletInvestigation(Base):
    """One 'run' of the investigation pipeline against a wallet address within a case."""

    __tablename__ = "wallet_investigations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    address: Mapped[str] = mapped_column(String(128), index=True)
    chain: Mapped[Chain] = mapped_column(Enum(Chain))
    seed_tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    max_hops: Mapped[int] = mapped_column(Integer, default=3)

    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued|running|complete|failed
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)          # balances, tx counts, first/last activity
    risk_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)      # Risk Fusion output
    patterns: Mapped[dict | None] = mapped_column(JSON, nullable=True)         # rule engine hits
    vasp_candidates: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # attribution engine output
    timeline: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cross_chain: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    copilot_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    case: Mapped["Case"] = relationship(back_populates="wallets")


class KnownEntity(Base):
    """VASP / Entity Intelligence Database: one row per known cluster or address."""

    __tablename__ = "known_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128), index=True)
    entity_type: Mapped[str] = mapped_column(String(32))  # vasp|exchange|dex|mixer|bridge|custodian|scam|ransomware
    chain: Mapped[Chain] = mapped_column(Enum(Chain))
    address: Mapped[str] = mapped_column(String(128), index=True)
    source: Mapped[str] = mapped_column(String(256))       # e.g. "CryptoScamDB", "Chainabuse", "manual attribution"
    source_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String(16), default="attributed")  # observed|inferred|attributed|confirmed

    __table_args__ = ()


class CaseNote(Base):
    __tablename__ = "case_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    author_id: Mapped[str] = mapped_column(ForeignKey("investigators.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    case: Mapped["Case"] = relationship(back_populates="notes")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"))
    wallet_investigation_id: Mapped[str | None] = mapped_column(ForeignKey("wallet_investigations.id"), nullable=True)
    alert_type: Mapped[str] = mapped_column(String(64))   # reaches_vasp|reaches_mixer|bridge_hop|high_risk_pattern|new_intermediary
    severity: Mapped[str] = mapped_column(String(16))     # info|low|medium|high|critical
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    case: Mapped["Case"] = relationship(back_populates="alerts")
