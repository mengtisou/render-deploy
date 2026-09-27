# RealAI trading plans · XAUUSD (OANDA)

Backtest: 30 Aug → 25 Sep 2026 (20 days), spread 0.18–0.22 included. 1 point = 0.10 in price.

## Plan A · KTR 15m + OFX 5m (main plan)

Two independent systems, each trade taken on its own.

| | A1 · KTR 15m | A2 · OFX combo 5m |
|---|---|---|
| Script / chart | `realai_ktr.pine` on **15m** | `realai_kob.pine` on **5m** |
| Signal | KTR ❖ entry | ENTER LONG / SHORT (5 gates, 60% on OrderBlock 1.0, ±1.7K delta) |
| Entry | Pending LIMIT ±20 pts (10 candles, cancel if price runs 200 pts) | At the signal candle close |
| SL | 100 pts (10.00) | OFX rule: below / above the block (near) or the candle (far) |
| TP | 200 pts (20.00) | 10.00 (100 pts) |
| Risk | 0.5% per trade | 0.5% per trade |
| Result (20 days) | 84 trades · 43% · ≈ +240 (+24R) | 68 trades · 57% · +109.24 (+8.6R) |

**Total A ≈ +349 · 152 trades.** Break-even win rate: A1 33%, A2 depends on the SL size.

## Plan B · KOB-15 only (combo, fewer trades)

Trade only when the 15m KTR ❖ and the OFX combo agree (same direction).

| | |
|---|---|
| Script / chart | `realai_kob.pine` on **5m** (row "KOB-15 A+") |
| Signal | 15m KTR ❖ (closed ≤ 1 h before) + OFX ENTER combo (≤ 30 min apart) |
| Entry | Pending LIMIT: BUY close −20 pts / SELL close +20 pts, 10 candles, cancel at 200 pts run-away |
| SL | OFX rule level |
| TP | 20.00 (200 pts) from the fill |
| Risk | 0.5–1% per trade |
| Result (20 days) | 28 trades · 46% · +106.58 (+12R) · 2 missed |

Use it when you cannot watch the chart often, or on a prop-firm account with a tight daily loss limit.

## Plan C · Plan A + KOB-15 add-on (maximum)

Everything in Plan A, **plus** an extra position when KOB-15 appears.

| | |
|---|---|
| Base | A1 (KTR 15m) + A2 (OFX 5m), 0.5% each |
| Add-on | KOB-15 signal → 2nd position, +0.5%, pending LIMIT ±20, TP 20.00, SL OFX rule |
| Result (20 days) | ≈ +455 (A ≈ +349 + add-on +106.58) · 180 trades |

More profit, but up to 3 positions can be open at once → keep 0.5% per position.

## Which one to use

1. **Weeks 1–4:** Plan A on demo / small size. Watch the KOB-15 row.
2. **After 4 weeks:** if KOB-15 stays the best per trade → move to Plan C.
3. Plan B instead of A/C only for low screen time or strict prop-firm limits.

Rules for all plans: same spread setting in both scripts (0.18–0.22), no manual changes to SL, stop for the day after −3R.
