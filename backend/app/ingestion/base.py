"""
Common shape every chain adapter (Ethereum, Polygon, Bitcoin, ...) returns,
so the rest of the pipeline (normalization, graph engine, clustering,
pattern engine) never has to know which chain it's looking at.

This is the contract behind the "Provider Registry" block in the
architecture diagram (docs/ARCHITECTURE.md).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawTransaction:
    """Chain-agnostic transaction, already close to the target normalized schema."""

    tx_hash: str
    block_number: int
    timestamp: datetime
    from_address: str
    to_address: str | None
    asset: str                     # "ETH", "MATIC", "BTC", or a token symbol
    value: float                   # in human units (already divided by decimals)
    fee: float
    contract_address: str | None = None
    method: str | None = None
    direction: str | None = None   # set later, relative to the investigated wallet
    raw: dict = field(default_factory=dict)  # provider's original payload, kept for audit/report


@dataclass
class WalletSnapshot:
    address: str
    chain: str
    balance: float
    first_activity: datetime | None
    last_activity: datetime | None
    total_tx_count: int
    incoming_count: int
    outgoing_count: int
    counterparties: set[str]
    assets_used: set[str]


class ChainProvider(ABC):
    """One implementation per supported blockchain / EVM chain id."""

    chain_name: str

    @abstractmethod
    async def get_balance(self, address: str) -> float:
        ...

    @abstractmethod
    async def get_transactions(self, address: str, limit: int = 1000) -> list[RawTransaction]:
        ...

    async def get_wallet_snapshot(self, address: str) -> WalletSnapshot:
        """Default implementation built from get_balance + get_transactions.
        Providers can override this if their API offers a cheaper combined call."""
        balance = await self.get_balance(address)
        txs = await self.get_transactions(address)
        incoming = [t for t in txs if t.to_address and t.to_address.lower() == address.lower()]
        outgoing = [t for t in txs if t.from_address.lower() == address.lower()]
        counterparties = set()
        for t in txs:
            counterparties.add(t.from_address.lower())
            if t.to_address:
                counterparties.add(t.to_address.lower())
        counterparties.discard(address.lower())
        timestamps = [t.timestamp for t in txs]
        return WalletSnapshot(
            address=address,
            chain=self.chain_name,
            balance=balance,
            first_activity=min(timestamps) if timestamps else None,
            last_activity=max(timestamps) if timestamps else None,
            total_tx_count=len(txs),
            incoming_count=len(incoming),
            outgoing_count=len(outgoing),
            counterparties=counterparties,
            assets_used={t.asset for t in txs},
        )


class ProviderNotImplemented(ChainProvider):
    """Placeholder for chains the diagram anticipates (TRON) but the MVP
    deliberately does not wire up yet -- see docs/ARCHITECTURE.md,
    'Provider Registry' and the project's own MVP roadmap."""

    def __init__(self, chain_name: str):
        self.chain_name = chain_name

    async def get_balance(self, address: str) -> float:
        raise NotImplementedError(
            f"{self.chain_name} is registered but not implemented in this build. "
            f"Add an adapter in app/ingestion/ following ethereum_provider.py, "
            f"then register it in provider_registry.py."
        )

    async def get_transactions(self, address: str, limit: int = 1000) -> list[RawTransaction]:
        raise NotImplementedError(
            f"{self.chain_name} is registered but not implemented in this build."
        )
