# Patch for ktr_v4_backtest.py — "cheap side" filter (`cheap_max`)

Skips a ❖ that prints more than `cheap_max` KTR steps on the **cheap** side of OP
(BUY far below OP / SELL far above OP — catching a falling knife). `0` = off (default, same as now).

## Edit 1 — in `class Config`, right after `adx_min: float = 30.0`
```python
    cheap_max: float = 0.0         # 0 = off · skip ❖ more than N KTR steps on the cheap side of OP
```

## Edit 2 — in `simulate()`, right after the line `fl_b, fl_s = flow_ok(1), flow_ok(-1)`
```python
        loc_x = (ci - op) / stp if (have_op and stp == stp and stp > 0) else NAN
        chp_b = cfg.cheap_max <= 0 or loc_x != loc_x or -loc_x <= cfg.cheap_max    # BUY: cheap = below OP
        chp_s = cfg.cheap_max <= 0 or loc_x != loc_x or loc_x <= cfg.cheap_max     # SELL: cheap = above OP
```

## Edit 3 — in the two `sig_b = (...)` / `sig_s = (...)` lines, add the new check
`... and wk_b and fl_b and` → `... and wk_b and fl_b and chp_b and`
`... and wk_s and fl_s and` → `... and wk_s and fl_s and chp_s and`

Check: `python ktr_v4_backtest.py --show-settings` must list `cheap_max = 0.0`.
