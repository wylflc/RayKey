#!/usr/bin/env python3
"""重述前版本存档（OI-130）：取数脚本在覆盖旧行之前把旧行写进 `superseded/`，
建带侧按可得日选用「当时在用」的版本。

存档文件与取数产物同目录、同列，另加三列：
    superseded_at    旧行自此日起被新版本取代（三表 = 远端新 `UPDATE_DATE`；逐季面板 = 重取的证据日）
    archived_at_utc  写档时刻
    archive_source   probe（探针）／refetch（重取）／backup（`.bak` 回填）
同一 (键, superseded_at) 只存一次。数值列相对变动 < `MIN_CHANGE` 的行视为同一版本、不存档；
日期／代码／名称等元数据列不参与比较。"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

ARCHIVE_FIELDS = ("superseded_at", "archived_at_utc", "archive_source")
MIN_CHANGE = 0.005
_META_KEYS = ("DATE", "CODE", "NAME", "RETRIEVED", "SOURCE", "TABLE", "TYPE", "CURRENCY",
              "OPINION", "STATE", "ORG_", "SECUCODE", "MARKET", "TRADE_")


def is_meta(field: str) -> bool:
    upper = field.upper()
    return upper in {f.upper() for f in ARCHIVE_FIELDS} or any(k in upper for k in _META_KEYS)


def _num(value) -> float | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return 0.0                      # 报表里空即 0（东财对未披露项留空）
    try:
        f = float(text)
    except ValueError:
        return None
    return f if f == f else 0.0


def rows_differ(old: dict, new: dict, min_change: float = MIN_CHANGE) -> list[str]:
    """两行的数值列中相对变动 ≥ `min_change` 的列名（空列名列表 = 同一版本）。"""
    changed: list[str] = []
    for key, value in new.items():
        if is_meta(key) or key not in old:
            continue
        a, b = _num(old.get(key)), _num(value)
        if a is None or b is None:
            if (str(old.get(key) or "").strip()) != (str(value or "").strip()):
                changed.append(key)
            continue
        if a == b:
            continue
        if abs(a - b) / max(abs(a), abs(b)) >= min_change:
            changed.append(key)
    return changed


def load_archive(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _key(row: dict, key_fields: tuple[str, ...], superseded_at: str) -> tuple:
    parts = []
    for k in key_fields:
        v = (row.get(k) or "").strip()
        parts.append(v.zfill(6) if "code" in k.lower() else v[:10])
    return tuple(parts) + (superseded_at[:10],)


def archive_rows(path: Path, batch: list[tuple[dict, str]], source: str,
                 key_fields: tuple[str, ...]) -> int:
    """把 `batch = [(旧行, superseded_at)]` 追加到 `path`（列取并集、保序；重复键跳过）。返回新增行数。"""
    if not batch:
        return 0
    existing = load_archive(path)
    seen = {_key(r, key_fields, r.get("superseded_at") or "") for r in existing}
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    added: list[dict] = []
    for row, superseded_at in batch:
        key = _key(row, key_fields, superseded_at)
        if key in seen:
            continue
        seen.add(key)
        added.append({**row, "superseded_at": superseded_at[:10], "archived_at_utc": stamp, "archive_source": source})
    if not added:
        return 0
    fields: list[str] = []
    for row in existing + added:
        for k in row:
            if k not in fields:
                fields.append(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, restval="")
        writer.writeheader()
        writer.writerows(existing + added)
    return len(added)
