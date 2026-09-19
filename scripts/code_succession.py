#!/usr/bin/env python3
"""证券代码变更（同一上市主体换码）的参考表与派生规则（工作流 §8.3，OI-192）。

参考表 `data/reference/a_share_code_succession.csv`：一行一对 (旧码, 新码)，
`last_old_trading_date` = 旧码末个交易日，`first_new_trading_date` = 新码首个交易日。

两条派生规则，唯一实现在本文件：
1. **除权事件**：数据源只按现行代码返回事件，旧码查询为空。`expand_actions` 把新码名下
   除权日 ≤ 旧码末个交易日的事件复制为旧码行（名称取旧名），旧码已有同键行不覆盖；无除权日的
   预案行不复制。`fetch_ohlcv_history.flush_actions` 每次落盘前调用，`--apply-actions` 用于
   离线补写既有事件表。
2. **时点面板**：`check_panel` 校验旧码区间 `effective_to` 非空且 ≤ 旧码末个交易日、新码区间
   `effective_from` ≥ 新码首个交易日；违反即装配失败，须先改判定源，不在装配时静默裁剪。

用法::

    python3 scripts/code_succession.py --apply-actions            # 补写事件表并打印新增行数
    python3 scripts/code_succession.py --check-panel data/processed/pit_attention/panel_moat_bank_v6b.csv
"""
from __future__ import annotations

import argparse
import csv
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUCCESSION = ROOT / "data/reference/a_share_code_succession.csv"
ACTIONS_CSV = ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv"
FIELDS = ("old_code", "old_name", "new_code", "new_name",
          "last_old_trading_date", "first_new_trading_date", "source", "note")
_CODE = re.compile(r"^\d{6}$")


def load_succession(path: Path = SUCCESSION) -> list[dict[str, str]]:
    """读取并校验参考表；缺文件视为无换码对。"""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [f for f in FIELDS if f not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name} 缺列 {missing}")
        rows = [dict(r) for r in reader]
    seen_old: set[str] = set()
    for r in rows:
        r["old_code"], r["new_code"] = r["old_code"].zfill(6), r["new_code"].zfill(6)
        if not (_CODE.match(r["old_code"]) and _CODE.match(r["new_code"])) or r["old_code"] == r["new_code"]:
            raise ValueError(f"代码无效：{r['old_code']}→{r['new_code']}")
        last_old = date.fromisoformat(r["last_old_trading_date"])
        first_new = date.fromisoformat(r["first_new_trading_date"])
        if not last_old < first_new:
            raise ValueError(f"{r['old_code']}→{r['new_code']} 旧码末日须早于新码首日")
        if r["old_code"] in seen_old:
            raise ValueError(f"旧码重复：{r['old_code']}")
        seen_old.add(r["old_code"])
    return rows


def action_key(action: dict[str, str]) -> tuple[str, str]:
    """与 `fetch_ohlcv_history.action_key` 同义：(代码, 除权日[:rights])；预案行按 plan 键。"""
    ex = (action.get("ex_dividend_date") or "").strip()
    code = action.get("security_code", "").zfill(6)
    if ex:
        try:
            rights = float(action.get("rights_ratio") or 0) > 0
        except ValueError:
            rights = False
        return (code, f"{ex}:rights" if rights else ex)
    return (code, f"plan:{action.get('report_date', '')}:{action.get('plan_notice_date', '')}")


def expand_actions(rows: list[dict[str, str]],
                   pairs: list[dict[str, str]] | None = None) -> tuple[list[dict[str, str]], int]:
    """按换码表把新码名下、除权日 ≤ 旧码末个交易日的事件复制到旧码。返回 (全部行, 新增行数)。"""
    pairs = load_succession() if pairs is None else pairs
    if not pairs:
        return list(rows), 0
    existing = {action_key(r) for r in rows}
    added: list[dict[str, str]] = []
    for pair in pairs:
        cutoff = pair["last_old_trading_date"]
        for r in rows:
            ex = (r.get("ex_dividend_date") or "").strip()
            if r.get("security_code", "").zfill(6) != pair["new_code"] or not ex or ex > cutoff:
                continue
            clone = {**r, "security_code": pair["old_code"], "security_name": pair["old_name"]}
            key = action_key(clone)
            if key in existing:
                continue
            existing.add(key)
            added.append(clone)
    return list(rows) + added, len(added)


def check_panel(rows: list[dict[str, str]], pairs: list[dict[str, str]] | None = None) -> list[str]:
    """面板区间不得跨越换码日：旧码 `effective_to` 非空且 ≤ 旧码末日；新码 `effective_from` ≥ 新码首日。"""
    pairs = load_succession() if pairs is None else pairs
    defects: list[str] = []
    for pair in pairs:
        for r in rows:
            code = r.get("security_code", "").zfill(6)
            if code == pair["old_code"]:
                if not r.get("effective_to") or r["effective_to"] > pair["last_old_trading_date"]:
                    defects.append(f"{code} 区间 {r.get('effective_from')}~{r.get('effective_to') or '开放'} "
                                   f"晚于旧码末个交易日 {pair['last_old_trading_date']}")
            elif code == pair["new_code"] and r.get("effective_from", "") < pair["first_new_trading_date"]:
                defects.append(f"{code} 区间自 {r.get('effective_from')} 起，早于新码首个交易日 "
                               f"{pair['first_new_trading_date']}")
    return defects


def apply_actions_file(path: Path = ACTIONS_CSV) -> int:
    """离线把换码派生行写回事件表（顺序与取数脚本一致：按键排序）。返回新增行数。"""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader if r.get("security_code")]
    merged, added = expand_actions(rows)
    if added:
        by_key = {action_key(r): r for r in merged}
        tmp = path.with_name("." + path.name + ".succession")
        with tmp.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(by_key[k] for k in sorted(by_key))
        tmp.replace(path)
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply-actions", nargs="?", const=ACTIONS_CSV, type=Path, metavar="CSV",
                        help="把换码派生的旧码事件行写回事件表（缺省生产事件表）")
    parser.add_argument("--check-panel", type=Path, metavar="CSV", help="校验面板区间不跨越换码日")
    args = parser.parse_args()
    pairs = load_succession()
    print(f"换码对 {len(pairs)}：" + "、".join(f"{p['old_code']}→{p['new_code']}" for p in pairs))
    rc = 0
    if args.apply_actions:
        added = apply_actions_file(args.apply_actions)
        print(f"事件表 {args.apply_actions.relative_to(ROOT) if args.apply_actions.is_relative_to(ROOT) else args.apply_actions}：新增旧码事件行 {added}")
    if args.check_panel:
        with args.check_panel.open(newline="", encoding="utf-8-sig") as handle:
            defects = check_panel(list(csv.DictReader(handle)), pairs)
        print("面板校验：" + ("通过" if not defects else "；".join(defects)))
        rc = 1 if defects else 0
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
