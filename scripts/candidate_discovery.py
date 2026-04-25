"""
候选发现层 (Candidate Discovery Layer) — roadmap P0-3
─────────────────────────────────────────────────────
将候选来源统一为多层发现机制，不再只扫描固定池。

候选来源:
  - cex_anomaly:     OKX/Binance 涨跌幅异常标的
  - alpha_hot:       Binance Alpha 高活跃标的
  - gmgn_trending:   GMGN 热门代币（SOL/BSC）
  - gmgn_signal:     GMGN 聪明钱信号
  - gmgn_trenches:   GMGN Pump.fun 新币
  - key_coins:       用户配置的固定观察池

每个候选包含:
  - symbol
  - candidate_source (列表)
  - tradable_on_cex: bool
  - market_type: "cex_perp" | "onchain_spot" | "layer0_watch"
  - metadata (原始数据)
"""
from __future__ import annotations

from typing import Any


class Candidate:
    def __init__(
        self,
        symbol: str,
        candidate_sources: list[str],
        tradable_on_cex: bool = False,
        market_type: str = "layer0_watch",
        metadata: dict[str, Any] | None = None,
    ):
        self.symbol = symbol.upper()
        self.candidate_sources = list(candidate_sources)
        self.tradable_on_cex = tradable_on_cex
        self.market_type = market_type  # cex_perp / onchain_spot / layer0_watch
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "candidate_sources": self.candidate_sources,
            "tradable_on_cex": self.tradable_on_cex,
            "market_type": self.market_type,
            "metadata": self.metadata,
        }


def discover_candidates(
    all_tickers: list[dict],
    alpha_dict: dict,
    gmgn_sol_trending: list[dict],
    gmgn_bsc_trending: list[dict],
    gmgn_signals: list[dict],
    gmgn_trenches: list[dict],
    key_coins: list[str],
    top_anomaly_n: int = 20,
    top_alpha_n: int = 15,
) -> list[Candidate]:
    """
    Unified candidate discovery. Returns all candidates with source tags.
    """
    candidates: dict[str, Candidate] = {}

    def _ensure(sym: str, source: str, tradable: bool = False, mtype: str = "layer0_watch", meta=None):
        sym = sym.upper()
        if sym not in candidates:
            candidates[sym] = Candidate(
                symbol=sym,
                candidate_sources=[source],
                tradable_on_cex=tradable,
                market_type=mtype,
                metadata=meta or {},
            )
        else:
            if source not in candidates[sym].candidate_sources:
                candidates[sym].candidate_sources.append(source)
            # Upgrade tradability if any source says it's tradable
            if tradable:
                candidates[sym].tradable_on_cex = True
                candidates[sym].market_type = mtype

    # 1. CEX anomaly (top gainers + top losers)
    if all_tickers:
        sorted_tickers = sorted(all_tickers, key=lambda x: x.get("chg24h_pct", 0), reverse=True)
        for t in sorted_tickers[:top_anomaly_n]:
            _ensure(t["symbol"], "cex_anomaly", tradable=True, mtype="cex_perp", meta={"chg24h_pct": t.get("chg24h_pct")})
        for t in sorted_tickers[-top_anomaly_n:]:
            _ensure(t["symbol"], "cex_anomaly", tradable=True, mtype="cex_perp", meta={"chg24h_pct": t.get("chg24h_pct")})

    # 2. Alpha hot
    top_alpha = sorted(alpha_dict.items(), key=lambda item: item[1].get("count24h", 0), reverse=True)[:top_alpha_n]
    for sym, data in top_alpha:
        _ensure(sym, "alpha_hot", tradable=True, mtype="cex_perp", meta={"count24h": data.get("count24h"), "pct": data.get("pct")})

    # 3. Key coins (always included)
    for sym in key_coins:
        _ensure(sym, "key_coins", tradable=True, mtype="cex_perp")

    # 4. GMGN trending (SOL + BSC) — onchain only, may map to CEX later
    for token in gmgn_sol_trending + gmgn_bsc_trending:
        sym = str(token.get("symbol", "")).upper()
        if sym:
            _ensure(sym, "gmgn_trending", tradable=False, mtype="onchain_spot", meta={
                "chain": token.get("chain", "sol"),
                "address": token.get("address", ""),
                "price": token.get("price", 0),
                "liquidity": token.get("liquidity", 0),
            })

    # 5. GMGN signals — smart money signals
    for signal in gmgn_signals:
        sym = str(signal.get("token_symbol", "")).upper()
        if not sym:
            # Try to extract from address if available
            continue
        _ensure(sym, "gmgn_signal", tradable=False, mtype="onchain_spot", meta={
            "signal_type": signal.get("signal_type"),
            "trigger_mc": signal.get("trigger_mc"),
        })

    # 6. GMGN trenches — new tokens
    for token in gmgn_trenches:
        sym = str(token.get("symbol", "")).upper()
        if sym:
            _ensure(sym, "gmgn_trenches", tradable=False, mtype="layer0_watch", meta={
                "chain": token.get("chain", "sol"),
                "address": token.get("address", ""),
            })

    return list(candidates.values())


def prioritize_candidates(candidates: list[Candidate], min_coverage: int = 2) -> list[Candidate]:
    """
    Prioritize candidates that appear in multiple sources (共振).
    Returns candidates sorted by source coverage desc, then tradable first.
    """
    def _score(c: Candidate) -> tuple:
        # Tradable CEX perp gets highest priority
        # Then multi-source candidates
        # Then single-source
        return (
            1 if c.tradable_on_cex else 0,
            len(c.candidate_sources),
            c.symbol,
        )

    candidates.sort(key=_score, reverse=True)

    # Separate multi-source from single-source for report clarity
    multi = [c for c in candidates if len(c.candidate_sources) >= min_coverage]
    single = [c for c in candidates if len(c.candidate_sources) < min_coverage]

    return multi + single


def get_cex_symbols(candidates: list[Candidate]) -> list[str]:
    """Extract only CEX-tradable symbols for batch data fetch."""
    return [c.symbol for c in candidates if c.tradable_on_cex]


def get_onchain_symbols(candidates: list[Candidate]) -> list[str]:
    """Extract onchain-only symbols for Layer 0 tracking."""
    return [c.symbol for c in candidates if not c.tradable_on_cex]
