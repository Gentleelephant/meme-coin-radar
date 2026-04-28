from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .common import FetchStatus
except ImportError:
    from common import FetchStatus

try:
    from ..history_store import history_dir, load_recent_social_snapshot
except ImportError:
    from history_store import history_dir, load_recent_social_snapshot


PANews_CLI = Path("/Users/zhangpeng/.cc-switch/skills/panews/scripts/cli.mjs")
SURF_BIN = "surf"
CACHE_TTL_SECONDS = 1800

NARRATIVE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ai": ("ai", "agent", "gpt", "llm", "intelligence"),
    "politics": ("trump", "election", "sec", "regulation", "congress"),
    "meme": ("meme", "pepe", "dog", "cat", "woof"),
    "defi": ("defi", "swap", "yield", "lending", "liquidity"),
    "gaming": ("game", "gaming", "metaverse", "play"),
    "exchange": ("listing", "binance", "coinbase", "okx", "bybit"),
}


def _run_command(command: list[str], source: str, timeout: int = 20) -> tuple[str | None, FetchStatus]:
    t0 = time.time()
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        latency = (time.time() - t0) * 1000
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip()
            error_type = FetchStatus.COMMAND_NOT_FOUND if "command not found" in message.lower() else FetchStatus.SOURCE_UNAVAILABLE
            if "ENOTFOUND" in message or "getaddrinfo" in message.lower():
                error_type = FetchStatus.NETWORK
            return None, FetchStatus(ok=False, error_type=error_type, message=message, latency_ms=latency, source=source)
        return completed.stdout.strip(), FetchStatus(ok=True, latency_ms=latency, source=source)
    except FileNotFoundError as exc:
        latency = (time.time() - t0) * 1000
        return None, FetchStatus(ok=False, error_type=FetchStatus.COMMAND_NOT_FOUND, message=str(exc), latency_ms=latency, source=source)
    except subprocess.TimeoutExpired as exc:
        latency = (time.time() - t0) * 1000
        return None, FetchStatus(ok=False, error_type=FetchStatus.TIMEOUT, message=str(exc), latency_ms=latency, source=source)
    except Exception as exc:
        latency = (time.time() - t0) * 1000
        return None, FetchStatus.from_exception(exc, source=source)


def _parse_json_or_lines(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            if isinstance(data.get("data"), list):
                return [item for item in data.get("data", []) if isinstance(item, dict)]
            return [data]
    except json.JSONDecodeError:
        pass
    rows = []
    for line in raw.splitlines():
        clean = line.strip().strip("|").strip()
        if not clean or clean.startswith(("USAGE", "OPTIONS", "ARGUMENTS")):
            continue
        rows.append({"text": clean})
    return rows


def _cache_path(output_dir: Path, name: str) -> Path:
    path = history_dir(output_dir) / f"intel_cache_{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_cache(output_dir: Path, name: str, ttl_seconds: int = CACHE_TTL_SECONDS) -> dict[str, Any] | None:
    path = _cache_path(output_dir, name)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = int(payload.get("fetched_at", 0) or 0)
        if fetched_at > 0 and int(time.time()) - fetched_at <= ttl_seconds:
            return payload
    except json.JSONDecodeError:
        return None
    return None


def _save_cache(output_dir: Path, name: str, payload: dict[str, Any]) -> None:
    path = _cache_path(output_dir, name)
    path.write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False), encoding="utf-8")


def _provider_result(data: dict[str, Any], status: FetchStatus, confidence: float) -> dict[str, Any]:
    return {
        "ok": status.ok,
        "source": status.source,
        "fetched_at": int(time.time()),
        "latency_ms": round(status.latency_ms, 1),
        "confidence": confidence,
        "error_type": status.error_type if not status.ok else None,
        "message": status.message or None,
        "data": data,
    }


def fetch_panews_rankings(output_dir: Path, lang: str = "en", take: int = 10) -> dict[str, Any]:
    cached = _load_cache(output_dir, f"panews_rankings_{lang}")
    if cached:
        return cached
    raw, status = _run_command(
        ["node", str(PANews_CLI), "get-rankings", "--type", "daily", "--take", str(take), "--lang", lang],
        source="panews-rankings",
        timeout=25,
    )
    items = _parse_json_or_lines(raw)
    payload = _provider_result({"items": items}, status, confidence=0.75 if items else 0.25)
    _save_cache(output_dir, f"panews_rankings_{lang}", payload)
    return payload


def fetch_panews_hooks(output_dir: Path, lang: str = "en", take: int = 20) -> dict[str, Any]:
    cached = _load_cache(output_dir, f"panews_hooks_{lang}")
    if cached:
        return cached
    raw, status = _run_command(
        [
            "node",
            str(PANews_CLI),
            "get-hooks",
            "--category",
            "search-keywords,website-recommended-topic,homepage-tab",
            "--take",
            str(take),
            "--lang",
            lang,
        ],
        source="panews-hooks",
        timeout=25,
    )
    items = _parse_json_or_lines(raw)
    payload = _provider_result({"items": items}, status, confidence=0.8 if items else 0.25)
    _save_cache(output_dir, f"panews_hooks_{lang}", payload)
    return payload


def fetch_panews_news(symbol: str, lang: str = "en", take: int = 5) -> dict[str, Any]:
    raw, status = _run_command(
        ["node", str(PANews_CLI), "search-articles", symbol, "--take", str(take), "--lang", lang],
        source="panews-search-articles",
        timeout=25,
    )
    items = _parse_json_or_lines(raw)
    headlines = [str(item.get("title") or item.get("text") or "").strip() for item in items]
    headlines = [line for line in headlines if line]
    return _provider_result(
        {"article_count": len(headlines), "headlines": headlines[:take]},
        status,
        confidence=0.7 if headlines else 0.2,
    )


def fetch_panews_events(symbol: str, lang: str = "en", take: int = 10) -> dict[str, Any]:
    raw, status = _run_command(
        ["node", str(PANews_CLI), "list-events", "--search", symbol, "--take", str(take), "--lang", lang],
        source="panews-events",
        timeout=25,
    )
    items = _parse_json_or_lines(raw)
    titles = [str(item.get("title") or item.get("text") or "").strip() for item in items]
    titles = [title for title in titles if title]
    return _provider_result(
        {"event_count": len(titles), "event_titles": titles[:take]},
        status,
        confidence=0.65 if titles else 0.2,
    )


def fetch_panews_calendar(symbol: str, lang: str = "en", take: int = 10) -> dict[str, Any]:
    raw, status = _run_command(
        ["node", str(PANews_CLI), "list-calendar-events", "--search", symbol, "--take", str(take), "--lang", lang],
        source="panews-calendar",
        timeout=25,
    )
    items = _parse_json_or_lines(raw)
    flags = [str(item.get("category") or item.get("title") or item.get("text") or "").strip() for item in items]
    flags = [flag for flag in flags if flag]
    return _provider_result(
        {"calendar_count": len(flags), "calendar_flags": flags[:take]},
        status,
        confidence=0.65 if flags else 0.2,
    )


def fetch_panews_polymarket_snapshot(lang: str = "en") -> dict[str, Any]:
    raw, status = _run_command(
        ["node", str(PANews_CLI), "get-polymarket-highlights"],
        source="panews-polymarket-highlights",
        timeout=25,
    )
    items = _parse_json_or_lines(raw)
    texts = [str(item.get("title") or item.get("text") or item.get("boardName") or "").strip() for item in items]
    texts = [text for text in texts if text]
    return _provider_result(
        {"highlight_count": len(texts), "labels": texts[:10], "score": float(min(len(texts), 5)) if texts else None},
        status,
        confidence=0.6 if texts else 0.2,
    )


def fetch_surf_news(symbol: str, take: int = 5) -> dict[str, Any]:
    if shutil.which(SURF_BIN) is None:
        status = FetchStatus(ok=False, error_type=FetchStatus.OPTIONAL_UNAVAILABLE, message="surf CLI not installed", source="surf-news")
        return _provider_result({"article_count": 0, "headlines": [], "event_tags": []}, status, confidence=0.0)
    raw, status = _run_command(
        [SURF_BIN, "search-news", "--q", symbol, "--limit", str(take), "--json"],
        source="surf-news",
        timeout=25,
    )
    items = _parse_json_or_lines(raw)
    headlines = [str(item.get("title") or item.get("headline") or "").strip() for item in items]
    headlines = [line for line in headlines if line]
    return _provider_result(
        {"article_count": len(headlines), "headlines": headlines[:take], "event_tags": []},
        status,
        confidence=0.7 if headlines else 0.2,
    )


def fetch_surf_social(symbol: str) -> dict[str, Any]:
    if shutil.which(SURF_BIN) is None:
        status = FetchStatus(ok=False, error_type=FetchStatus.OPTIONAL_UNAVAILABLE, message="surf CLI not installed", source="surf-social")
        return _provider_result({"mentions_24h": 0, "mindshare_score": None, "sentiment_score": None, "kol_mentions": 0}, status, confidence=0.0)
    raw, status = _run_command(
        [SURF_BIN, "search-social", "--q", symbol, "--limit", "10", "--json"],
        source="surf-social",
        timeout=25,
    )
    items = _parse_json_or_lines(raw)
    mentions = len(items)
    return _provider_result(
        {"mentions_24h": mentions, "mindshare_score": None, "sentiment_score": None, "kol_mentions": 0},
        status,
        confidence=0.6 if mentions > 0 else 0.2,
    )


def _extract_panews_keywords(shared_context: dict[str, Any]) -> list[str]:
    hooks = (((shared_context.get("panews_hooks") or {}).get("data") or {}).get("items") or [])
    rankings = (((shared_context.get("panews_rankings") or {}).get("data") or {}).get("items") or [])
    keywords: list[str] = []
    for item in hooks + rankings:
        for key in ("text", "title", "keyword", "name"):
            value = str(item.get(key) or "").strip()
            if value:
                keywords.append(value)
    return keywords[:20]


def _classify_narratives(symbol: str, social_intel: dict[str, Any]) -> list[str]:
    haystack_parts = [symbol]
    for key in ("global_news_headlines", "panews_latest_headlines", "panews_topic_tags", "panews_editorial_keywords"):
        value = social_intel.get(key) or []
        if isinstance(value, list):
            haystack_parts.extend(str(item) for item in value)
    haystack = " ".join(haystack_parts).lower()
    labels = [label for label, words in NARRATIVE_KEYWORDS.items() if any(word in haystack for word in words)]
    return sorted(set(labels))


def _growth(current: int | None, previous: dict[str, Any] | None, field: str) -> float:
    if current is None:
        return 0.0
    previous_value = int((previous or {}).get(field) or 0)
    if previous_value <= 0:
        return 0.0
    return (current - previous_value) / previous_value


def _source_degraded(results: dict[str, dict[str, Any]]) -> list[str]:
    degraded = [name for name, result in results.items() if not result.get("ok")]
    return sorted(degraded)


def fetch_social_intel(
    symbol: str,
    output_dir: Path,
    chain: str | None = None,
    token_address: str | None = None,
    okx_context: dict[str, Any] | None = None,
    panews_context: dict[str, Any] | None = None,
    lang: str = "en",
) -> dict[str, Any]:
    snapshot_timestamp = int(time.time())
    panews_context = panews_context or {}
    surf_news = fetch_surf_news(symbol)
    surf_social = fetch_surf_social(symbol)
    panews_news = fetch_panews_news(symbol, lang=lang)
    panews_events = fetch_panews_events(symbol, lang=lang)
    panews_calendar = fetch_panews_calendar(symbol, lang=lang)
    panews_board = panews_context.get("panews_polymarket") or fetch_panews_polymarket_snapshot(lang=lang)

    okx_context = okx_context or {}
    okx_x_rank = okx_context.get("okx_x_rank")
    kol_onchain_activity_count = int(okx_context.get("kol_onchain_activity_count") or 0)
    smart_money_onchain_activity_count = int(okx_context.get("smart_money_onchain_activity_count") or 0)

    shared_keywords = _extract_panews_keywords(panews_context)
    panews_articles = ((panews_news.get("data") or {}).get("headlines") or [])
    surf_headlines = ((surf_news.get("data") or {}).get("headlines") or [])
    social_mentions_24h = int((surf_social.get("data") or {}).get("mentions_24h") or 0)
    social_mentions_6h = max(int(round(social_mentions_24h * 0.25)), 0)

    previous_6h = load_recent_social_snapshot(output_dir, symbol, hours_back=6)
    previous_24h = load_recent_social_snapshot(output_dir, symbol, hours_back=24)
    social_growth_6h = _growth(social_mentions_6h, previous_6h, "social_mentions_6h")
    social_growth_24h = _growth(social_mentions_24h, previous_24h, "social_mentions_24h")

    heat_direction = "stable"
    if social_growth_6h > 0.5:
        heat_direction = "accelerating"
    elif social_growth_6h < -0.2:
        heat_direction = "cooling"

    source_results = {
        "surf_news": surf_news,
        "surf_social": surf_social,
        "panews_news": panews_news,
        "panews_events": panews_events,
        "panews_calendar": panews_calendar,
        "panews_polymarket": panews_board,
        "panews_rankings": panews_context.get("panews_rankings", {}),
        "panews_hooks": panews_context.get("panews_hooks", {}),
    }
    degraded = _source_degraded(source_results)
    available_sources = sum(1 for result in source_results.values() if result.get("ok"))
    if available_sources / max(len(source_results), 1) < 0.5:
        social_mentions_24h = 0
        social_mentions_6h = 0
        social_growth_6h = 0.0
        social_growth_24h = 0.0
        heat_direction = "unknown"

    keyword_set = {str(keyword).strip().lower() for keyword in shared_keywords if str(keyword).strip()}

    merged = {
        "symbol": symbol,
        "chain": chain,
        "token_address": token_address,
        "snapshot_timestamp": snapshot_timestamp,
        "social_mentions_6h": social_mentions_6h,
        "social_mentions_24h": social_mentions_24h,
        "social_growth_6h": social_growth_6h,
        "social_growth_24h": social_growth_24h,
        "social_heat_direction": heat_direction,
        "mindshare_score": (surf_social.get("data") or {}).get("mindshare_score"),
        "sentiment_score": (surf_social.get("data") or {}).get("sentiment_score"),
        "global_news_count_24h": int((surf_news.get("data") or {}).get("article_count") or 0),
        "global_news_headlines": surf_headlines,
        "global_news_event_tags": (surf_news.get("data") or {}).get("event_tags") or [],
        "panews_article_count_24h": int((panews_news.get("data") or {}).get("article_count") or 0),
        "panews_latest_headlines": panews_articles,
        "panews_hot_rank": 1 if symbol.lower() in keyword_set else None,
        "panews_topic_tags": [],
        "panews_editorial_keywords": shared_keywords,
        "panews_event_count_7d": int((panews_events.get("data") or {}).get("event_count") or 0),
        "panews_calendar_flags": (panews_calendar.get("data") or {}).get("calendar_flags") or [],
        "kol_social_mentions": int((surf_social.get("data") or {}).get("kol_mentions") or 0),
        "kol_onchain_activity_count": kol_onchain_activity_count,
        "smart_money_onchain_activity_count": smart_money_onchain_activity_count,
        "public_board_snapshot_score": (panews_board.get("data") or {}).get("score"),
        "public_board_snapshot_labels": (panews_board.get("data") or {}).get("labels") or [],
        "narrative_labels": [],
        "source_confidence": {key: float(result.get("confidence", 0.0) or 0.0) for key, result in source_results.items()},
        "status": {key: {"ok": result.get("ok"), "error_type": result.get("error_type"), "source": result.get("source"), "fetched_at": result.get("fetched_at")} for key, result in source_results.items()},
        "source_degraded": degraded,
        "social_heat_unavailable": available_sources == 0,
    }
    merged["narrative_labels"] = _classify_narratives(symbol, merged)
    return merged


def build_shared_intel_context(output_dir: Path, lang: str = "en") -> dict[str, Any]:
    return {
        "panews_rankings": fetch_panews_rankings(output_dir, lang=lang),
        "panews_hooks": fetch_panews_hooks(output_dir, lang=lang),
        "panews_polymarket": fetch_panews_polymarket_snapshot(lang=lang),
    }
