"""
候选发现层 (Candidate Discovery Layer)
─────────────────────────────────────
以 OKX OnchainOS 为主发现层，Binance Alpha 只做热度补强。

主入口:
  - okx_hot:       OKX trending 热门榜
  - okx_x:         OKX X mentions 热门榜
  - okx_signal:    OKX 聚合买入信号
  - okx_tracker:   OKX 聪明钱交易流
  - alpha_hot:     Binance Alpha 热度补强
  - key_coins:     固定观察池
"""
from __future__ import annotations

from typing import Any


class Candidate:
    def __init__(
        self,
        symbol: str,
        candidate_sources: list[str],
        tradable_on_cex: bool = False,
        market_type: str = "onchain_spot",
        token_address: str = "",
        chain: str = "",
        metadata: dict[str, Any] | None = None,
    ):
        self.symbol = symbol.upper()
        self.candidate_sources = list(candidate_sources)
        self.tradable_on_cex = tradable_on_cex
        self.market_type = market_type
        self.token_address = token_address
        self.chain = chain
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "candidate_sources": self.candidate_sources,
            "tradable_on_cex": self.tradable_on_cex,
            "market_type": self.market_type,
            "token_address": self.token_address,
            "chain": self.chain,
            "metadata": self.metadata,
        }


def _norm_chain(chain: Any) -> str:
    raw = str(chain or "").strip().lower()
    chain_map = {
        "501": "solana",
        "1": "ethereum",
        "56": "bsc",
        "8453": "base",
    }
    return chain_map.get(raw, raw)


def _hot_meta(item: dict[str, Any], okx_hot_rank: int | None = None, okx_x_rank: int | None = None) -> dict[str, Any]:
    return {
        "chain": _norm_chain(item.get("chain") or item.get("chainIndex")),
        "address": str(item.get("token_address") or item.get("tokenContractAddress") or ""),
        "okx_hot_rank": okx_hot_rank,
        "okx_x_rank": okx_x_rank,
        "onchain_data": {
            "hot_token": item,
        },
    }


def discover_candidates(
    okx_hot_tokens: list[dict] | None = None,
    okx_x_tokens: list[dict] | None = None,
    okx_signals: list[dict] | None = None,
    okx_tracker_activities: list[dict] | None = None,
    alpha_dict: dict | None = None,
    key_coins: list[str] | tuple[str, ...] = (),
    all_tickers: list[dict] | None = None,
    gmgn_sol_trending: list[dict] | None = None,
    gmgn_bsc_trending: list[dict] | None = None,
    gmgn_signals: list[dict] | None = None,
    gmgn_trenches: list[dict] | None = None,
    top_alpha_n: int = 15,
) -> list[Candidate]:
    candidates: dict[str, Candidate] = {}
    alpha_dict = alpha_dict or {}

    def _ensure(
        sym: str,
        source: str,
        token_address: str = "",
        chain: str = "",
        tradable: bool = False,
        mtype: str = "onchain_spot",
        meta: dict[str, Any] | None = None,
    ) -> Candidate:
        symbol = sym.upper().strip()
        if not symbol:
            raise ValueError("symbol is required")
        candidate = candidates.get(symbol)
        if candidate is None:
            candidate = Candidate(
                symbol=symbol,
                candidate_sources=[source],
                tradable_on_cex=tradable,
                market_type=mtype,
                token_address=token_address,
                chain=chain,
                metadata=meta or {},
            )
            candidates[symbol] = candidate
        else:
            if source not in candidate.candidate_sources:
                candidate.candidate_sources.append(source)
            if tradable:
                candidate.tradable_on_cex = True
                candidate.market_type = mtype
            if token_address and not candidate.token_address:
                candidate.token_address = token_address
            if chain and not candidate.chain:
                candidate.chain = chain
            if meta:
                existing = candidate.metadata.get("onchain_data", {})
                incoming = meta.get("onchain_data", {})
                candidate.metadata = {**candidate.metadata, **meta}
                candidate.metadata["onchain_data"] = {**existing, **incoming}
        return candidate

    for index, item in enumerate(okx_hot_tokens or [], 1):
        symbol = str(item.get("tokenSymbol") or item.get("symbol") or "").upper()
        if not symbol:
            continue
        meta = _hot_meta(item, okx_hot_rank=index)
        _ensure(
            symbol,
            "okx_hot",
            token_address=meta["address"],
            chain=meta["chain"],
            tradable=False,
            mtype="onchain_spot",
            meta=meta,
        )

    for index, item in enumerate(okx_x_tokens or [], 1):
        symbol = str(item.get("tokenSymbol") or item.get("symbol") or "").upper()
        if not symbol:
            continue
        meta = _hot_meta(item, okx_x_rank=index)
        _ensure(
            symbol,
            "okx_x",
            token_address=meta["address"],
            chain=meta["chain"],
            tradable=False,
            mtype="onchain_spot",
            meta=meta,
        )

    for item in okx_signals or []:
        token = item.get("token", {}) if isinstance(item.get("token"), dict) else {}
        symbol = str(token.get("symbol") or item.get("symbol") or "").upper()
        if not symbol:
            continue
        chain = _norm_chain(item.get("chain") or item.get("chainIndex"))
        address = str(token.get("tokenAddress") or item.get("tokenAddress") or "")
        _ensure(
            symbol,
            "okx_signal",
            token_address=address,
            chain=chain,
            tradable=False,
            mtype="onchain_spot",
            meta={"chain": chain, "address": address, "onchain_data": {"signal": item}},
        )

    for item in okx_tracker_activities or []:
        changed = item.get("changedTokenInfo", [])
        token_info = changed[0] if isinstance(changed, list) and changed and isinstance(changed[0], dict) else {}
        symbol = str(token_info.get("tokenSymbol") or item.get("tokenSymbol") or "").upper()
        if not symbol:
            continue
        chain = _norm_chain(item.get("chain") or item.get("chainIndex"))
        address = str(token_info.get("tokenAddress") or item.get("tokenAddress") or "")
        _ensure(
            symbol,
            "okx_tracker",
            token_address=address,
            chain=chain,
            tradable=False,
            mtype="onchain_spot",
            meta={"chain": chain, "address": address, "onchain_data": {"tracker": item}},
        )

    top_alpha = sorted(alpha_dict.items(), key=lambda item: item[1].get("count24h", 0), reverse=True)[:top_alpha_n]
    for sym, data in top_alpha:
        _ensure(
            str(sym),
            "alpha_hot",
            tradable=True,
            mtype="cex_perp",
            meta={"binance_alpha_symbol": str(sym).upper(), "alpha_data": data},
        )

    for sym in key_coins:
        _ensure(str(sym), "key_coins", tradable=True, mtype="cex_perp")

    # Keep compatibility with older discovery sources if they are still supplied.
    for legacy in (gmgn_sol_trending or []) + (gmgn_bsc_trending or []):
        symbol = str(legacy.get("symbol") or "").upper()
        if not symbol:
            continue
        _ensure(
            symbol,
            "legacy_gmgn",
            token_address=str(legacy.get("address") or ""),
            chain=_norm_chain(legacy.get("chain")),
            tradable=False,
            mtype="onchain_spot",
            meta={"chain": _norm_chain(legacy.get("chain")), "address": str(legacy.get("address") or ""), "gmgn_data": legacy},
        )

    return list(candidates.values())


def prioritize_candidates(candidates: list[Candidate], min_coverage: int = 2) -> list[Candidate]:
    def _score(c: Candidate) -> tuple[int, int, str]:
        return (
            len(c.candidate_sources),
            1 if c.tradable_on_cex else 0,
            c.symbol,
        )

    return sorted(candidates, key=_score, reverse=True)


def get_cex_symbols(candidates: list[Candidate]) -> list[str]:
    return [c.symbol for c in candidates if c.tradable_on_cex]


def get_onchain_symbols(candidates: list[Candidate]) -> list[str]:
    return [c.symbol for c in candidates if not c.tradable_on_cex]
