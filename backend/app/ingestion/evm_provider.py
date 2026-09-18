"""
EVM chain adapter, backed by the Etherscan API v2.

As of the August 2025 migration, Etherscan unified Ethereum, Polygon and
50+ other EVM chains behind ONE API key and ONE base path
(https://api.etherscan.io/v2/api), distinguished only by a `chainid`
query parameter. That is exactly why the project brief's two asks --
"keep the live integrations to just Etherscan + Bitcoin" and "the
architecture supports Ethereum/Polygon/TRON/Bitcoin" -- aren't in
tension for Ethereum/Polygon: they are the same adapter, parameterized
by chain id. TRON is a non-EVM chain with its own API and is left as a
registered-but-unimplemented provider (see base.py, provider_registry.py).

Docs: https://docs.etherscan.io/v2-migration
Note: the free tier caps some list endpoints at 1000 records/request
(reduced from 10,000 in July 2026) -- get_transactions below paginates
around that automatically.
"""
from datetime import datetime, timezone

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.ingestion.base import ChainProvider, RawTransaction

ETHERSCAN_V2_BASE = "https://api.etherscan.io/v2/api"

CHAIN_IDS = {
    "ethereum": 1,
    "polygon": 137,
}

NATIVE_ASSET = {
    "ethereum": "ETH",
    "polygon": "MATIC",
}

PAGE_SIZE = 1000  # free-tier ceiling per request, see module docstring


class EVMProvider(ChainProvider):
    def __init__(self, chain_name: str):
        if chain_name not in CHAIN_IDS:
            raise ValueError(f"EVMProvider does not support chain '{chain_name}'")
        self.chain_name = chain_name
        self.chain_id = CHAIN_IDS[chain_name]
        self.native_asset = NATIVE_ASSET[chain_name]
        self.settings = get_settings()

    def _params(self, **extra) -> dict:
        return {
            "chainid": self.chain_id,
            "apikey": self.settings.etherscan_api_key,
            **extra,
        }

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    async def _get(self, params: dict) -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(ETHERSCAN_V2_BASE, params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_balance(self, address: str) -> float:
        data = await self._get(self._params(module="account", action="balance", address=address, tag="latest"))
        wei = int(data.get("result", 0) or 0)
        return wei / 1e18

    async def get_transactions(self, address: str, limit: int = 1000) -> list[RawTransaction]:
        """Normal + ERC-20/ERC-721 token transfers, merged and time-sorted.
        Internal (contract-forwarded) transfers are a documented extension
        point -- add an `action=txlistinternal` call here the same way if a
        case needs them (Pro-tier endpoint as of the 2026 changelog)."""
        txs: list[RawTransaction] = []

        normal = await self._paginate(address, action="txlist")
        for row in normal:
            txs.append(self._row_to_tx(row, asset=self.native_asset, value_decimals=18))

        tokens = await self._paginate(address, action="tokentx")
        for row in tokens:
            decimals = int(row.get("tokenDecimal") or 18)
            txs.append(
                self._row_to_tx(row, asset=row.get("tokenSymbol", "TOKEN"), value_decimals=decimals, is_token=True)
            )

        txs.sort(key=lambda t: t.timestamp)
        return txs[:limit] if limit else txs

    async def _paginate(self, address: str, action: str) -> list[dict]:
        rows: list[dict] = []
        page = 1
        while True:
            data = await self._get(
                self._params(
                    module="account",
                    action=action,
                    address=address,
                    startblock=0,
                    endblock=99_999_999,
                    page=page,
                    offset=PAGE_SIZE,
                    sort="asc",
                )
            )
            result = data.get("result")
            if not isinstance(result, list) or not result:
                break
            rows.extend(result)
            if len(result) < PAGE_SIZE:
                break
            page += 1
            if page > 10:  # hard ceiling: 10k rows/action is plenty for a 1-3 hop trace
                break
        return rows

    @staticmethod
    def _row_to_tx(row: dict, asset: str, value_decimals: int, is_token: bool = False) -> RawTransaction:
        value_raw = int(row.get("value", 0) or 0)
        return RawTransaction(
            tx_hash=row.get("hash", ""),
            block_number=int(row.get("blockNumber", 0) or 0),
            timestamp=datetime.fromtimestamp(int(row.get("timeStamp", 0) or 0), tz=timezone.utc),
            from_address=(row.get("from") or "").lower(),
            to_address=(row.get("to") or "").lower() or None,
            asset=asset,
            value=value_raw / (10 ** value_decimals),
            fee=(int(row.get("gasUsed", 0) or 0) * int(row.get("gasPrice", 0) or 0)) / 1e18
            if not is_token
            else 0.0,
            contract_address=(row.get("contractAddress") or None),
            method=row.get("functionName") or row.get("methodId") or None,
            raw=row,
        )
