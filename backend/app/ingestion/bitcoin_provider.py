"""
Bitcoin adapter, backed by Blockstream's Esplora API (free, keyless,
self-hostable -- https://github.com/Blockstream/esplora/blob/master/API.md).

Any other Esplora-compatible indexer (your own node + esplora, mempool.space's
API, which is API-compatible) works too: just change BITCOIN_API_BASE_URL.

Bitcoin transactions are modeled as UTXOs (inputs/outputs), not simple
from->to transfers like an EVM chain. get_transactions() below flattens
each transaction into one RawTransaction per (input-owner -> output) edge
touching the investigated address, which is what the rest of the
pipeline (graph engine, pattern engine) expects. The full UTXO detail is
kept in `raw` for anything that needs it (e.g. the common-input
clustering heuristic in app/clustering/btc_clustering.py).
"""
from datetime import datetime, timezone

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.ingestion.base import ChainProvider, RawTransaction

SATS_PER_BTC = 100_000_000


class BitcoinProvider(ChainProvider):
    chain_name = "bitcoin"

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.bitcoin_api_base_url.rstrip("/")

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    async def _get(self, path: str) -> dict | list:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{self.base_url}{path}")
            resp.raise_for_status()
            return resp.json()

    async def get_balance(self, address: str) -> float:
        data = await self._get(f"/address/{address}")
        stats = data.get("chain_stats", {})
        funded = stats.get("funded_txo_sum", 0)
        spent = stats.get("spent_txo_sum", 0)
        return (funded - spent) / SATS_PER_BTC

    async def get_transactions(self, address: str, limit: int = 1000) -> list[RawTransaction]:
        rows: list[dict] = []
        last_seen = None
        while len(rows) < limit:
            path = f"/address/{address}/txs" if last_seen is None else f"/address/{address}/txs/chain/{last_seen}"
            page = await self._get(path)
            if not page:
                break
            rows.extend(page)
            last_seen = page[-1]["txid"]
            if len(page) < 25:  # Esplora returns up to 25/page; short page == done
                break

        txs: list[RawTransaction] = []
        for row in rows[:limit]:
            txs.extend(self._flatten(row, address))
        txs.sort(key=lambda t: t.timestamp)
        return txs

    @staticmethod
    def _flatten(row: dict, focus_address: str) -> list[RawTransaction]:
        """One RawTransaction per input-owner -> output edge that touches
        focus_address, so a fan-in/fan-out UTXO transaction still produces
        graph-friendly directed edges."""
        status = row.get("status", {})
        ts = status.get("block_time")
        timestamp = (
            datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(tz=timezone.utc)
        )
        fee_btc = row.get("fee", 0) / SATS_PER_BTC
        vin = row.get("vin", [])
        vout = row.get("vout", [])

        inputs = [
            (v.get("prevout", {}).get("scriptpubkey_address"), v.get("prevout", {}).get("value", 0) / SATS_PER_BTC)
            for v in vin
            if v.get("prevout")
        ]
        outputs = [
            (o.get("scriptpubkey_address"), o.get("value", 0) / SATS_PER_BTC)
            for o in vout
            if o.get("scriptpubkey_address")
        ]

        involves_focus_as_input = any(a == focus_address for a, _ in inputs)
        involves_focus_as_output = any(a == focus_address for a, _ in outputs)

        edges: list[RawTransaction] = []
        if involves_focus_as_input:
            # outgoing: focus wallet is (one of) the spender(s) -> each output
            for out_addr, out_val in outputs:
                if out_addr == focus_address:
                    continue  # change back to self, not a counterparty edge
                edges.append(
                    RawTransaction(
                        tx_hash=row.get("txid", ""),
                        block_number=status.get("block_height", 0) or 0,
                        timestamp=timestamp,
                        from_address=focus_address,
                        to_address=out_addr,
                        asset="BTC",
                        value=out_val,
                        fee=fee_btc,
                        raw=row,
                    )
                )
        if involves_focus_as_output:
            # incoming: each distinct input owner -> focus wallet
            input_owners = {a for a, _ in inputs if a and a != focus_address}
            focus_received = sum(v for a, v in outputs if a == focus_address)
            for owner in input_owners or {"unknown_input"}:
                edges.append(
                    RawTransaction(
                        tx_hash=row.get("txid", ""),
                        block_number=status.get("block_height", 0) or 0,
                        timestamp=timestamp,
                        from_address=owner,
                        to_address=focus_address,
                        asset="BTC",
                        value=focus_received,
                        fee=fee_btc,
                        raw=row,
                    )
                )
        return edges
