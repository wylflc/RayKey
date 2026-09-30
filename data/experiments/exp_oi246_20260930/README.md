# OI-246 谷底守卫典型股票：识别规则、走势规避与止损

预登记见 `preregister.md`（提交 cb6d4c1c），读数见 `readings.md`，日志 §12.301。

- `analyze.py`：读 `../exp_oi245c_20260930/observations3.csv`，划谷底段与入选月，按正式公司行动前复权行情算走势特征与名义仓位的四种止损，出典型股票表、全段列联表与触发后回报。输出 `episodes.csv`、`readings.json`、`readings.md`。
- R1 的公允性 λ 见 `../exp_oi245c_20260930/readings3.md` 第三节；现行 BASE 下谷底守卫周期的去向（读数第 4 条）见 `../exp_oi247_20260930/readings.md` 第七节。

    python3 analyze.py
