# OI-179 source-path audit

The audited defect is matching a corporate-action date only against a stock's quote dates. An absent stock quote must not discard an event. Separate financial-data revisions, execution assumptions, and unrelated historical research conventions are not certified by this check.

| Path | Calendar and disposition |
|---|---|
| `backtest_valuation_strategy.exright_affine` | Fixed: consumes every action in `(quote_date, final_quote_date]`, including several events inside one suspension. Events on the quote itself are already reflected in its price. |
| `adjusted_moving_averages`, `adjusted_close_series`, `volume_ratio_series` | Share the corrected affine mapping; direct-window, quote-boundary, no-action and split-volume tests cover these consumers. |
| `backtest_valuation_strategy.daily_returns` | Fixed: share multipliers and net cash compose in time order between quotes through `quote_action_factors`; rights subscription cash is deducted. |
| `moat_param_lab.total_return_index` | Fixed: all between-quote events, cash reinvestment only at the next valid quote, rights subscription deduction. Used by `selection_edge_audit`, `panel_tier_forward`, `swap_regime_control` and several other common research readers. Prior outputs retain their original vintage. |
| `pv_episode_forward.return_indices`; `whipsaw_swap_diag.holding_return_path` | Already iterate complete action dates between quotes. The former was used as an independent cash/share index check against all corrected total-return series. |
| `rank_episode_forward` | Now explicitly re-evaluates a frozen cohort using current event handling; original-table equality and historical trend mismatches remain diagnostics. Strict historical reproduction is opt-in and requires historical code/inputs. |
| `swap_chop_guard.rebase`; isolated MA-slope `SlopeGuard.rebase` | Already iterate complete event dates in `(start, end]`; their input MAs inherit the corrected native mapping. |
| `experimental/vp_signal_lab` | Events iterate a market-wide calendar (falling forward for absent market dates), then apply to all earlier quote positions. Does not use the defective per-stock `events.get(quote_day)` pattern; its distinct historical multiplicative adjustment convention is not changed. |
| `apply_corporate_actions`, residual-clear/drawdown ledger replay | Traverse market/NAV dates, not just that stock's quote dates. Exact-day event access therefore does not discard an event merely because that stock is suspended. Targeted test verifies cash, shares and stop-anchor delivery without a stock quote. This does not constitute a full audit of suspended-position marking assumptions. |
| Production daily scanner | Reads vendor-adjusted daily prices; it does not use `exright_affine`. OI-179 fixes the local historical implementation to follow the existing basis requirement. |

`held_suspension_events.json` records examples where full BASE anchor paths held a stock across a no-quote event, supporting the distinction between portfolio-calendar event delivery and quote-series adjustment. `quote_gap_events.csv` and `affected_codes.csv` provide the complete quote-gap audit. All numerical scopes and validation limits are disclosed in the report.
