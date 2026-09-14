#!/usr/bin/env python3
"""Register a user-confirmed net execution for §9.3.3 cooldown activation."""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from lot_cooldown import DEFAULT_EXECUTIONS, DEFAULT_STATE, read_rows, record_execution
from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("execution-id", "signal-date", "as-of", "code", "name", "side", "rule"):
        parser.add_argument("--" + name, required=True)
    for name in ("shares", "price", "tranche"):
        parser.add_argument("--" + name, type=float, required=True)
    parser.add_argument("--executions", type=Path, default=DEFAULT_EXECUTIONS)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_DECISION_LOG)
    args = parser.parse_args()
    record = dict(execution_id=args.execution_id, signal_date=args.signal_date,
                  execution_date=args.as_of, security_code=args.code, security_name=args.name,
                  side=args.side, rule=args.rule, shares=args.shares, price=args.price, tranche=args.tranche)
    try:
        added = record_execution(record, args.executions, args.state)
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    if not any(r["decision_id"] == f"cooldown:{args.execution_id}" for r in read_rows(args.log_file)):
        append_decision_log(args.log_file, [dict(
            logged_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            workflow_stage="execution_cooldown", run_id=f"cooldown:{args.execution_id}", as_of=args.as_of,
            security_code=args.code.zfill(6), security_name=args.name,
            decision_type="cooldown_execution", decision_result="confirmed",
            summary_reason=f"原信号 {args.signal_date}；{args.side}/{args.rule} 实际净成交 {args.shares:g} 股 @ {args.price:g}；档位 {args.tranche:g}",
            input_files=str(args.executions), output_file=str(args.executions),
            operator_or_script="scripts/record_cooldown_execution.py", workflow_version=WORKFLOW_VERSION,
            decision_id=f"cooldown:{args.execution_id}")])
    print("已登记确认成交；当天已扫描则重跑当天扫描。" if added else "相同成交已登记，本次无重复写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
