#!/usr/bin/env python3
"""§9.1 第 6 步：把 docs/000_daily_scan_log.md 中信号日早于 --before 的条目移入 data/archive/。

用法：
    python3 scripts/archive_daily_scan_log.py --before 2026-09-01            # 预览
    python3 scripts/archive_daily_scan_log.py --before 2026-09-01 --apply    # 新建归档文件
    python3 scripts/archive_daily_scan_log.py --before 2026-09-01 --apply \
        --into data/archive/daily_scan_log_2026-08-13_to_2026-08-30.md      # 并入既有归档并扩展其日期范围

条目以 `## ` 标题起始，条目日期取标题中的第一个 YYYY-MM-DD；标题无日期的条目视为当前条目、不移动。
条目顺序（最新在前）原样保留；归档文件只追加不改写既有条目；`data/archive/README.md` 的索引行同步更新。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "docs/000_daily_scan_log.md"
ARCHIVE_DIR = ROOT / "data/archive"
README = ARCHIVE_DIR / "README.md"
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
VERSION = re.compile(r"v\d+\.\d+")


def split_entries(text: str) -> tuple[str, list[str]]:
    """返回 (标题前的正文, [条目...])；每个条目自 `## ` 行起到下一条目前。"""
    parts = re.split(r"(?m)^(?=## )", text)
    preamble = "" if parts and parts[0].startswith("## ") else parts.pop(0) if parts else ""
    return preamble, parts


def entry_date(entry: str) -> str | None:
    match = DATE.search(entry.split("\n", 1)[0])
    return match.group(0) if match else None


def plan(text: str, before: str) -> tuple[list[str], list[str]]:
    preamble, entries = split_entries(text)
    keep, move = [], []
    for entry in entries:
        day = entry_date(entry)
        (move if day and day < before else keep).append(entry)
    return [preamble] + keep if preamble else keep, move


def header(start: str, end: str, versions: list[str]) -> str:
    span = f"（{versions[0]} ~ {versions[-1]}）" if versions else ""
    return (f"# 每日扫描日志归档 {start} ~ {end}{span}\n\n"
            f"> 自 `docs/000_daily_scan_log.md` 按工作流程 §9.1 第 6 步月度归档移出的条目，原样保留。当前条目只在 `docs/000_daily_scan_log.md`。\n\n")


def sorted_versions(entries: list[str]) -> list[str]:
    found = {v for e in entries for v in VERSION.findall(e.split("\n", 1)[0])}
    return sorted(found, key=lambda v: tuple(int(x) for x in v[1:].split(".")))


def update_readme(old_name: str | None, new_name: str, start: str, end: str) -> None:
    text = README.read_text(encoding="utf-8")
    row = f"| `{new_name}` | {start} ~ {end} 每日扫描日志 | 自 `docs/000_daily_scan_log.md` 按 §9.1 第 6 步移出 |\n"
    if old_name and f"`{old_name}`" in text:
        text = re.sub(rf"^\| `{re.escape(old_name)}` \|.*\n", row, text, count=1, flags=re.MULTILINE)
    elif f"`{new_name}`" not in text:
        anchor = re.search(r"^\| `daily_scan_log_[^`]+` \|.*\n", text, re.MULTILINE)
        text = text[:anchor.end()] + row + text[anchor.end():] if anchor else text.rstrip("\n") + "\n" + row
    README.write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--before", required=True, help="归档信号日早于此日期（YYYY-MM-DD，通常为本月 1 日）的条目")
    ap.add_argument("--apply", action="store_true", help="不给只预览")
    ap.add_argument("--into", type=Path, help="并入既有归档文件（其日期范围随之扩展并改名）")
    ap.add_argument("--log", type=Path, default=LOG)
    args = ap.parse_args()
    if not DATE.fullmatch(args.before):
        ap.error("--before 须为 YYYY-MM-DD")
    text = args.log.read_text(encoding="utf-8")
    keep, move = plan(text, args.before)
    if not move:
        print(f"没有信号日早于 {args.before} 的条目")
        return 0
    dates = sorted(entry_date(e) for e in move)
    for entry in move:
        print("移出:", entry.split("\n", 1)[0].strip()[:100])
    if args.into:
        old = args.into.read_text(encoding="utf-8")
        first = old.split("\n", 1)[0]
        old_dates = DATE.findall(first)
        if len(old_dates) < 2:
            ap.error("--into 文件首行须含「起 ~ 止」两个日期")
        start, end = min(old_dates[0], dates[0]), max(old_dates[1], dates[-1])
        versions = sorted_versions(move + split_entries(old)[1])
        head, body = old.split("\n", 1)
        new_text = header(start, end, versions) + body.split("\n", 2)[2].lstrip("\n") if body.startswith("\n>") else header(start, end, versions) + body.lstrip("\n")
        # 归档内同样最新在前：移出的条目晚于既有条目，放在既有条目之前
        preamble, old_entries = split_entries(new_text)
        new_text = preamble + "".join(move) + "".join(old_entries)
        target = ARCHIVE_DIR / f"daily_scan_log_{start}_to_{end}.md"
        old_name = args.into.name
    else:
        start, end = dates[0], dates[-1]
        target = ARCHIVE_DIR / f"daily_scan_log_{start}_to_{end}.md"
        if target.exists():
            ap.error(f"{target} 已存在；用 --into 并入")
        new_text = header(start, end, sorted_versions(move)) + "".join(move)
        old_name = None
    print(f"归档文件: {target.relative_to(ROOT)}（{len(move)} 条，{start} ~ {end}）")
    if not args.apply:
        print("预览模式，未写入；加 --apply 执行")
        return 0
    target.write_text(new_text, encoding="utf-8")
    if args.into and args.into.resolve() != target.resolve():
        args.into.unlink()
    args.log.write_text("".join(keep), encoding="utf-8")
    update_readme(old_name, target.name, start, end)
    print("已写入；日志剩余", len(split_entries("".join(keep))[1]), "条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
