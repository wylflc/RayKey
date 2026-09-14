"""Confirmed-fill cooldown state and shared opportunity arithmetic (§9.3.3)."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
import hashlib
import math
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "data/processed/daily_cooldown_state.csv"
DEFAULT_EXECUTIONS = ROOT / "data/processed/cooldown_executions.csv"
SIDES = ("buy", "sell")
STATE_FIELDS = ["security_code", "security_name", "side", "remaining_skips",
                "remaining_before", "applied_trade_date", "execution_key"]
EXECUTION_FIELDS = ["execution_id", "signal_date", "execution_date", "security_code",
                    "security_name", "side", "rule", "shares", "price", "tranche"]


def cooldown_skips(amount: float, tranche: float) -> int:
    if not math.isfinite(amount) or not math.isfinite(tranche) or amount < 0 or tranche <= 0:
        raise ValueError("冷却金额须有限且非负，档位须有限且为正")
    return max(0, round(amount / tranche) - 1)


def lot_ratio_ready(counters: dict, code: str, lot_value: float, tranche: float) -> bool:
    """Consume an existing counter; planning never starts a new one."""
    if not all(math.isfinite(v) and v > 0 for v in (lot_value, tranche)):
        return False
    if counters.get(code, 0) > 0:
        counters[code] -= 1
        return False
    return True


class Opportunities:
    """One signal day: revisiting a code cannot consume a second opportunity."""
    def __init__(self, counters):
        self.counters = counters
        self.checked = {}

    def ready(self, code):
        if code not in self.checked:
            self.checked[code] = lot_ratio_ready(self.counters, code, 1., 1.)
        return self.checked[code]


def read_rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def atomic_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                     dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def normalize_execution(record):
    row = {k: str(record.get(k, "")) for k in EXECUTION_FIELDS}
    if not row["execution_id"].strip() or not row["security_code"].isdigit() or len(row["security_code"]) > 6:
        raise ValueError("须提供本地 execution_id 和六位代码")
    row["security_code"] = row["security_code"].zfill(6)
    signal, execution = (date.fromisoformat(row[k]) for k in ("signal_date", "execution_date"))
    if execution <= signal:
        raise ValueError("成交日必须晚于原信号日")
    if row["side"] not in SIDES or row["rule"] not in ({"buy"} if row["side"] == "buy" else {"gain", "exit", "swap"}):
        raise ValueError("冷却只支持买入、涨幅减持、出名单、换仓净成交")
    row["signal_date"], row["execution_date"] = signal.isoformat(), execution.isoformat()
    for key in ("shares", "price", "tranche"):
        value = float(row[key])
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} 必须为正有限数；无成交不登记")
        row[key] = format(value, ".15g")
    return row


def execution_groups(rows, as_of):
    groups = {}
    identities, plans = set(), {}
    for source in rows:
        r = normalize_execution(source)
        if r["execution_id"] in identities:
            raise ValueError("成交凭据中存在重复 execution_id")
        identities.add(r["execution_id"])
        day_key = (r["security_code"], r["side"], r["execution_date"])
        if plans.setdefault(day_key, r["signal_date"]) != r["signal_date"]:
            raise ValueError("同股同侧同日须归属一个原始计划，不能混记多个信号日")
        if r["execution_date"] > as_of:
            continue
        key = (r["security_code"], r["side"], r["execution_date"], r["signal_date"])
        groups.setdefault(key, []).append(r)
    latest = {}
    for (code, side, day, signal), records in sorted(groups.items(), key=lambda item: item[0][2:]):
        tranches = {float(r["tranche"]) for r in records}
        if len(tranches) != 1:
            raise ValueError("同一计划的成交档位不一致")
        amount = sum(float(r["shares"]) * float(r["price"]) for r in records)
        identity = json.dumps(sorted(r["execution_id"] for r in records))
        tranche = tranches.pop()
        mean_price = amount / sum(float(r["shares"]) for r in records)
        latest[(side, code)] = dict(key=hashlib.sha256(identity.encode()).hexdigest(),
                                   skips=(cooldown_skips(amount, tranche) if mean_price * 100 > tranche else 0),
                                   name=records[-1]["security_name"], date=day)
    return latest


@dataclass
class CooldownBook:
    path: Path
    executions: Path
    as_of: str
    before: dict
    names: dict
    sources: dict
    writable: bool
    state_hash: str
    executions_hash: str

    @classmethod
    def load(cls, path, as_of, executions=None):
        date.fromisoformat(as_of)
        path = Path(path)
        executions = Path(executions) if executions is not None else path.with_name(DEFAULT_EXECUTIONS.name)
        if path.resolve() == executions.resolve():
            raise ValueError("成交凭据与冷却快照必须使用不同文件")
        rows, fills = read_rows(path), read_rows(executions)
        before = {side: {} for side in SIDES}
        names, sources = {}, {}
        writable = not any(r["applied_trade_date"] > as_of for r in rows)
        writable &= not any(r["execution_date"] > as_of for r in fills)
        if writable:
            old = {(r.get("side") or "buy", r["security_code"]): r for r in rows}
            latest = execution_groups(fills, as_of)
            for key in old.keys() | latest.keys():
                side, code = key
                prior, receipt = old.get(key, {}), latest.get(key)
                if receipt is None:
                    if any(float(prior.get(k) or 0) > 0 for k in ("remaining_skips", "remaining_before")):
                        raise ValueError(f"{code}/{side} 非零冷却没有确认成交凭据，须先核验迁移")
                    continue
                if prior.get("execution_key") == receipt["key"]:
                    field = "remaining_before" if prior["applied_trade_date"] == as_of else "remaining_skips"
                    remaining = int(prior[field])
                else:
                    if prior and prior["applied_trade_date"] > receipt["date"]:
                        raise ValueError("补记历史成交后须重放受影响扫描，不能直接重置当前冷却")
                    remaining = receipt["skips"]
                before[side][code] = remaining
                names[code] = receipt["name"]
                sources[key] = receipt["key"]
        return cls(path, executions, as_of, before, names, sources, writable,
                   fingerprint(path), fingerprint(executions))

    def save(self, after):
        if not self.writable:
            raise ValueError("历史重放不可写当前冷却状态")
        if (fingerprint(self.path), fingerprint(self.executions)) != (self.state_hash, self.executions_hash):
            raise ValueError("扫描期间冷却或成交凭据发生变化，请重跑")
        rows = []
        for (side, code), source in sorted(self.sources.items()):
            remaining = after[side].get(code, 0)
            if not 0 <= remaining <= self.before[side].get(code, 0):
                raise ValueError("扫描不得启动或增加冷却")
            rows.append(dict(security_code=code, security_name=self.names.get(code, ""), side=side,
                             remaining_skips=remaining, remaining_before=self.before[side].get(code, 0),
                             applied_trade_date=self.as_of, execution_key=source))
        for side in SIDES:
            if any(n > 0 and (side, c) not in self.sources for c, n in after[side].items()):
                raise ValueError("扫描产生了没有确认成交来源的冷却")
        # A marker preserves the date even when there have never been cooldown fills.
        if not rows:
            rows.append(dict(security_code="", security_name="", side="buy", remaining_skips=0,
                             remaining_before=0, applied_trade_date=self.as_of, execution_key=""))
        atomic_csv(self.path, rows, STATE_FIELDS)


def record_execution(record, path=DEFAULT_EXECUTIONS, state_path=DEFAULT_STATE):
    """Append a confirmed net fill. Repeat IDs are idempotent, conflicts fail."""
    row = normalize_execution(record)
    path, state_path = Path(path), Path(state_path)
    if path.resolve() == state_path.resolve():
        raise ValueError("成交凭据与冷却快照必须使用不同文件")
    rows = read_rows(path)
    duplicate = [r for r in rows if r["execution_id"] == row["execution_id"]]
    if duplicate:
        if duplicate != [row]:
            raise ValueError("execution_id 已登记且内容冲突")
        return False
    last_scan = max((r["applied_trade_date"] for r in read_rows(state_path)), default="")
    if row["execution_date"] < last_scan:
        raise ValueError("成交早于最近扫描，须重放受影响区间后登记")
    execution_groups(rows + [row], row["execution_date"])
    atomic_csv(path, rows + [row], EXECUTION_FIELDS)
    return True
