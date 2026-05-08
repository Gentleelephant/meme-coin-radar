"""
JSON output size guard with progressive downsampling.

Prevents result.json from exceeding JSON serialization limits
by progressively reducing data fidelity when size thresholds are exceeded.
"""

from __future__ import annotations

import json


RESULT_JSON_MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5MB
RESULT_JSON_MAX_SIZE_MB = RESULT_JSON_MAX_SIZE_BYTES / (1024 * 1024)


def estimate_json_size(data: dict | list) -> int:
    """Estimate JSON size in bytes without serializing."""
    return len(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))


def downsample_candidate(candidate: dict) -> dict:
    """
    Downsample a candidate by removing large nested data structures.
    Keeps core scoring and decision fields, removes raw K-line data.
    """
    downsized = candidate.copy()

    # Remove large meta fields
    meta = downsized.get("meta", {})
    if meta:
        preserved_meta = {}
        for key in ("market_cap", "turnover_ratio", "day_pos", "count24h", "address", "chain"):
            if key in meta:
                preserved_meta[key] = meta[key]
        downsized["meta"] = preserved_meta

    # Remove trade_plan detailed fields if present
    trade_plan = downsized.get("trade_plan", {})
    if trade_plan:
        preserved_plan = {
            k: v for k, v in trade_plan.items()
            if k not in ("entry_low", "entry_high", "stop_loss", "take_profit_1", "take_profit_2")
        }
        downsized["trade_plan"] = preserved_plan

    # Remove execution_result detailed fields
    exec_result = downsized.get("execution_result")
    if exec_result:
        downsized["execution_result"] = {
            "status": exec_result.get("status"),
            "mode": exec_result.get("mode"),
        }

    return downsized


def downsample_results(results: list[dict], target_size_bytes: int | None = None) -> list[dict]:
    """
    Progressive downsampling: reduce results until target size is achieved.
    Returns downsized results list.
    """
    if not results:
        return results

    target_size = target_size_bytes if target_size_bytes is not None else RESULT_JSON_MAX_SIZE_BYTES

    # First pass: downsample all candidates
    downsized = [downsample_candidate(r) for r in results]

    # Check if downsizing helped
    estimated_size = estimate_json_size(downsized)
    if estimated_size <= target_size:
        return downsized

    # Second pass: drop lowest-scored candidates until size is acceptable
    sorted_by_score = sorted(enumerate(downsized), key=lambda x: x[1].get("final_score", 0) or 0, reverse=True)
    kept = []
    removed_count = 0

    for _idx, item in sorted_by_score:
        if estimate_json_size(kept + [item]) <= target_size:
            kept.append(item)
        else:
            removed_count += 1

    if removed_count:
        print(f" ⚠️ 结果数据过大，降采样后移除了 {removed_count} 个低分候选")
    return sorted(kept, key=lambda x: x.get("final_score", 0) or 0, reverse=True)


def save_with_size_guard(
    name: str,
    data: dict | list,
    scan_dir,
    max_size_bytes: int | None = None,
) -> str:
    """
    Save JSON with size guard. If size exceeds limit, apply progressive downsampling.
    If still too large, split into meta and raw files.
    """
    max_size = max_size_bytes if max_size_bytes is not None else RESULT_JSON_MAX_SIZE_BYTES
    max_size_mb = max_size / (1024 * 1024)

    estimated_size = estimate_json_size(data)

    if estimated_size <= max_size:
        content = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        return _write_file(name, content, scan_dir)

    print(f" ⚠️ {name} 预估大小 {estimate_json_size(data) / (1024*1024):.2f}MB > {max_size_mb:.1f}MB，开始降采样...")

    if isinstance(data, list):
        downsized = downsample_results(data, max_size)
        content = json.dumps(downsized, indent=2, ensure_ascii=False, default=str)

        if len(content.encode("utf-8")) <= max_size:
            return _write_file(name, content, scan_dir)

        # Still too large: split into meta and full
        print(f" ⚠️ 降采样后仍超过限制，拆分输出文件...")
        meta_only: list[dict] = []
        for item in downsized:
            meta_item = {
                "radar_version": item.get("radar_version"),
                "run_mode": item.get("run_mode"),
                "symbol": item.get("symbol"),
                "decision": item.get("decision"),
                "final_score": item.get("final_score"),
                "oos": item.get("oos"),
                "ers": item.get("ers"),
                "direction": item.get("direction"),
                "confidence": item.get("confidence"),
                "can_enter": item.get("can_enter"),
            }
            meta_only.append(meta_item)

        _write_file("result_meta.json", json.dumps(meta_only, indent=2, ensure_ascii=False, default=str), scan_dir)
        _write_file("result_full.json", content, scan_dir)
        print(f" ✅ 已拆分：result_meta.json（核心评分）+ result_full.json（完整数据）")
        return str(scan_dir / name)
    else:
        # For dict data, try downsampling by removing large nested structures
        if isinstance(data, dict):
            downsized_dict: dict = {}
            for key, value in data.items():
                if key in ("candidates", "results") and isinstance(value, list):
                    downsized_dict[key] = downsample_results(value, max_size)
                else:
                    downsized_dict[key] = value

            content = json.dumps(downsized_dict, indent=2, ensure_ascii=False, default=str)
            if len(content.encode("utf-8")) <= max_size:
                return _write_file(name, content, scan_dir)

        print(f" ⚠️ 无法通过降采样解决，建议检查数据源")
        content = json.dumps(data, indent=2, ensure_ascii=False, default=str)[:max_size]
        return _write_file(name, content, scan_dir)


def _write_file(name: str, content: str, scan_dir) -> str:
    path = scan_dir / name
    path.write_text(content, encoding="utf-8")
    return str(path)