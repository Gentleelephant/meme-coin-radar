"""
资产映射层 (Asset Mapping Layer) — roadmap P0-5
────────────────────────────────────────────────
建立 OKX OnchainOS 链上代币与 Binance/CEX 合约 Symbol 的稳定映射，防止同名币/假币污染评分。

映射置信度等级:
  - high:     明确匹配（contract_address 已知 + symbol 完全一致 + 链上流动性验证）
  - medium:   symbol 一致，无地址验证
  - low:      symbol 相似或社区常用简称
  - none:     无映射关系

规则:
  - low 置信度映射禁止直接进入主评分，仅做观察
  - medium 以上可进入主评分但标记 mapping_confidence
  - 若同一 symbol 在多个链出现，取最高流动性者
"""
from __future__ import annotations

from typing import Any, Optional


class AssetMapping:
    """Maps onchain tokens to CEX symbols with confidence scoring."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"

    def __init__(self):
        # Known verified mappings (manual curation / historical verification)
        # Format: onchain_symbol -> {cex_symbol, chain, contract_address, confidence}
        self._verified: dict[str, dict[str, Any]] = {
            # Add known mappings as they are verified
            # "PEPE": {"onchain_symbol": "PEPE", "chain": "eth", "address": "0x...", "confidence": "high"},
        }
        # Symbol normalization overrides (common aliases)
        self._aliases: dict[str, str] = {
            # "BTC": "BTC",
            # "ETH": "ETH",
        }

    def map_token(
        self,
        onchain_symbol: str,
        chain: str = "",
        contract_address: str = "",
        cex_symbol_list: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Map an OKX/onchain token to potential Binance/CEX symbols.
        Returns mapping dict with confidence.
        """
        normalized_symbol = onchain_symbol.upper()
        cex_list = [s.upper() for s in (cex_symbol_list or [])]

        # Direct verified mapping
        if normalized_symbol in self._verified:
            v = self._verified[normalized_symbol]
            return {
                "onchain_symbol": normalized_symbol,
                "cex_symbol": v.get("cex_symbol", normalized_symbol),
                "chain": v.get("chain", chain),
                "contract_address": v.get("address", contract_address),
                "confidence": v.get("confidence", self.HIGH),
                "mapping_method": "verified_registry",
            }

        # Exact symbol match in CEX list
        if normalized_symbol in cex_list:
            return {
                "onchain_symbol": normalized_symbol,
                "cex_symbol": normalized_symbol,
                "chain": chain,
                "contract_address": contract_address,
                "confidence": self.MEDIUM,
                "mapping_method": "exact_symbol_match",
            }

        # Alias match
        if normalized_symbol in self._aliases:
            alias = self._aliases[normalized_symbol]
            return {
                "onchain_symbol": normalized_symbol,
                "cex_symbol": alias,
                "chain": chain,
                "contract_address": contract_address,
                "confidence": self.LOW,
                "mapping_method": "alias",
            }

        # Fuzzy / partial match (e.g., "PEPE2.0" vs "PEPE")
        for cex_sym in cex_list:
            if normalized_symbol.startswith(cex_sym) or cex_sym.startswith(normalized_symbol):
                # Too fuzzy — mark as low confidence
                return {
                    "onchain_symbol": normalized_symbol,
                    "cex_symbol": cex_sym,
                    "chain": chain,
                    "contract_address": contract_address,
                    "confidence": self.LOW,
                    "mapping_method": "fuzzy_prefix",
                }

        # No mapping
        return {
            "onchain_symbol": normalized_symbol,
            "cex_symbol": None,
            "chain": chain,
            "contract_address": contract_address,
            "confidence": self.NONE,
            "mapping_method": "none",
        }

    def apply_to_candidates(self, candidates: list, cex_symbol_list: list[str]) -> list:
        """
        Enrich candidate list with mapping info.
        Returns enriched dicts.
        """
        enriched = []
        for c in candidates:
            if getattr(c, "tradable_on_cex", False):
                # Already tradable, no mapping needed
                enriched.append({
                    "symbol": c.symbol,
                    "tradable_on_cex": True,
                    "market_type": getattr(c, "market_type", "cex_perp"),
                    "strategy_mode": getattr(c, "strategy_mode", "meme_onchain"),
                    "mapping_confidence": "native",
                    "candidate_sources": getattr(c, "candidate_sources", []),
                    "metadata": getattr(c, "metadata", {}),
                })
                continue

            # Try mapping onchain token to CEX
            meta = getattr(c, "metadata", {})
            mapping = self.map_token(
                onchain_symbol=c.symbol,
                chain=meta.get("chain", ""),
                contract_address=meta.get("address", ""),
                cex_symbol_list=cex_symbol_list,
            )

            # If medium+ confidence mapping found, upgrade to tradable
            if mapping["confidence"] in (self.HIGH, self.MEDIUM):
                enriched.append({
                    "symbol": mapping["cex_symbol"] or c.symbol,
                    "tradable_on_cex": True,
                    "market_type": "cex_perp",
                    "strategy_mode": getattr(c, "strategy_mode", "meme_onchain"),
                    "mapping_confidence": mapping["confidence"],
                    "candidate_sources": getattr(c, "candidate_sources", []),
                    "binance_alpha_symbol": mapping["cex_symbol"],
                    "has_binance_execution": True,
                    "metadata": {**meta, "mapping": mapping},
                })
            else:
                enriched.append({
                    "symbol": c.symbol,
                    "tradable_on_cex": False,
                    "market_type": getattr(c, "market_type", "layer0_watch"),
                    "strategy_mode": getattr(c, "strategy_mode", "meme_onchain"),
                    "mapping_confidence": mapping["confidence"],
                    "candidate_sources": getattr(c, "candidate_sources", []),
                    "binance_alpha_symbol": mapping.get("cex_symbol"),
                    "has_binance_execution": False,
                    "metadata": {**meta, "mapping": mapping},
                })

        return enriched


# Singleton instance
_default_mapper = AssetMapping()


def map_token(*args, **kwargs) -> dict[str, Any]:
    return _default_mapper.map_token(*args, **kwargs)


def apply_to_candidates(candidates: list, cex_symbol_list: list[str]) -> list:
    return _default_mapper.apply_to_candidates(candidates, cex_symbol_list)
