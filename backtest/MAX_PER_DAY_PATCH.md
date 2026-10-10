# Patch for ktr_v4_backtest.py — "Max ❖ trades per day" (`max_day`)

Places only the first N ❖ trades / pending orders of each trading day; later ❖ that day are skipped
(counted as "daily limit" skips). `0` = no limit (default, same as now).

## Edit 1 — in `class Config`, right after `day_sl: float = 300.0`
```python
    max_day: int = 0               # 0 = no limit · max ❖ trades / orders per trading day
```

## Edit 2 — in `class St`, right after `weSkip: int = 0`
```python
    day_n: int = 0
```

## Edit 3 — in `simulate()`, in the `if new_day:` block, the line
`s.dayPts, s.dayW, s.dayL, s.dayStop, s.dayWhy = 0.0, 0, 0, False, ""`
add right below it (same indentation):
```python
                s.day_n = 0
```

## Edit 4 — in the "2) a confirmed ❖ opens a trade" loop, replace
```python
                if cfg.day_on and s.dayStop:
                    s.skipDay += 1
```
with
```python
                if (cfg.day_on and s.dayStop) or (cfg.max_day > 0 and s.day_n >= cfg.max_day):
                    s.skipDay += 1
```

## Edit 5 — a few lines lower, right after `s.sesTrId = ses_id`
```python
                    s.day_n += 1
```

Check: `python ktr_v4_backtest.py --show-settings` lists `max_day = 0`, then compare
```
python ktr_v4_backtest.py XAUUSD_oanda_15m.csv --set t_con=false --set htf=1h --set adx_on=false --set wick=false
python ktr_v4_backtest.py XAUUSD_oanda_15m.csv --set t_con=false --set htf=1h --set adx_on=false --set wick=false --set max_day=2
```
