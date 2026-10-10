#!/usr/bin/env python3
"""
KTR v4 sweep + walk-forward check  (uses ktr_v4_backtest.py + ktr_backtest.py from the same folder)
==================================================================================================
Runs many settings in one go and shows each one split in two periods, so you can see if a setting
only works in the months it was picked on (overfitting) or in BOTH periods (real edge).

    python ktr_v4_sweep.py XAUUSD_oanda_15m.csv --split "2026-07-01"
    python ktr_v4_sweep.py XAUUSD_oanda_15m.csv --split "2026-07-01" --grid htf=off,1h --grid adx_on=false,true
    python ktr_v4_sweep.py XAUUSD_oanda_15m.csv --split "2026-07-01" --set ses_lon_on=true --grid cheap_max=0,1
    python ktr_v4_sweep.py XAUUSD_oanda_15m.csv --preset      # the standard list of tests (see PRESET below)

--set   key=value          fixed for every run (same keys as ktr_v4_backtest.py --show-settings)
--grid  key=v1,v2,...      every combination of all --grid lists is run
--split "YYYY-MM-DD HH:MM" in --tz; trades that END before it = IN-SAMPLE (A), from it on = OUT-OF-SAMPLE (B)

Columns: trades, win rate, net R and max drawdown R for A, B and ALL, plus months in profit.
Keep a setting only if it is positive in BOTH A and B (and better than the baseline in both).
"""
from __future__ import annotations

import argparse
import itertools
import sys
from dataclasses import fields

import pandas as pd

try:
    import ktr_v4_backtest as kv
    kb = kv.kb
except ImportError as e:
    sys.exit(f"Put this file next to ktr_v4_backtest.py and ktr_backtest.py ({e}).")

# name, overrides   (applied on top of --set; the first line is the baseline everything is compared with)
PRESET = [
    ("baseline: v3 logic (all sessions, all ◇, no filters)",
     "ses_lon_on=true t_con=true t_mic=true wick=false adx_on=false htf=off"),
    ("current v4 defaults", ""),
    ("v4 + 1H trend", "htf=1h"),
    ("v4 + 1H trend, ADX/wick off", "htf=1h adx_on=false wick=false"),
    ("v4 + cheap side max 1 step", "cheap_max=1"),
    ("v4 + 1H trend + cheap max 1", "htf=1h cheap_max=1"),
    ("v4 + 1H + cheap 1, London ON", "htf=1h cheap_max=1 ses_lon_on=true"),
    ("v4 + 1H + cheap 1, micro OFF", "htf=1h cheap_max=1 t_mic=false"),
    ("v4 + 1H + cheap 1, ADX/wick off", "htf=1h cheap_max=1 adx_on=false wick=false"),
    ("1H trend only (all sessions, all ◇)", "ses_lon_on=true t_con=true t_mic=true wick=false adx_on=false htf=1h"),
    ("1H + cheap 1 only (all sessions, all ◇)",
     "ses_lon_on=true t_con=true t_mic=true wick=false adx_on=false htf=1h cheap_max=1"),
]


def parse_val(cur, v):
    if isinstance(cur, bool):
        return v.lower() in ("1", "true", "yes", "on", "y")
    if isinstance(cur, int):
        return int(v)
    if isinstance(cur, float):
        return float(v)
    return v


def stats(rows, sl):
    """rows: (exit_time, pts) sorted by time -> trades, win%, net R, max DD R, months +/total."""
    if not rows:
        return dict(n=0, wr=0.0, net=0.0, dd=0.0, mo="0/0")
    net = pk = dd = 0.0
    w = l = 0
    mo = {}
    for t, p in rows:
        net += p
        pk = max(pk, net)
        dd = max(dd, pk - net)
        w += p > 0
        l += p < 0
        mo[(t.year, t.month)] = mo.get((t.year, t.month), 0.0) + p
    return dict(n=len(rows), wr=100.0 * w / max(w + l, 1), net=net / sl, dd=dd / sl,
                mo=f"{sum(1 for v in mo.values() if v > 0)}/{len(mo)}")


def run_one(df, base_items, extra, args, tf_ms, day_id, split):
    cfg = kv.Config()
    kv.apply_overrides(cfg, base_items + extra)
    cfg.spread_cmp = False          # only the picked spread -> faster
    cfg.rep_on = False
    if cfg.vol_on and not (df["volume"] > 0).any():
        cfg.vol_on = False
    res = kv.simulate(df, cfg, day_id, tf_ms, args.session_tz, args.session_hour)
    idx = df.index.tz_convert(args.tz)
    rows = sorted((idx[r[2]], r[8]) for r in res["M"].rows)          # (exit candle time, pts)
    a = [r for r in rows if split is None or r[0] < split]
    b = [r for r in rows if split is not None and r[0] >= split]
    return stats(a, cfg.sl), stats(b, cfg.sl), stats(rows, cfg.sl)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--data-tz", default="UTC")
    ap.add_argument("--tz", default="Asia/Bangkok")
    ap.add_argument("--session-tz", default="America/New_York")
    ap.add_argument("--session-hour", type=float, default=17.0)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--split", help="in --tz: before = A (in-sample), from = B (out-of-sample)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--grid", action="append", default=[], metavar="KEY=V1,V2")
    ap.add_argument("--preset", action="store_true", help="run the standard list of tests")
    args = ap.parse_args()

    df = kb.load_csv(args.csv, args.data_tz)
    if args.start:
        df = df[df.index >= pd.Timestamp(args.start, tz=args.tz)]
    if args.end:
        df = df[df.index <= pd.Timestamp(args.end, tz=args.tz)]
    step = df.index.to_series().diff().median()
    if step < pd.Timedelta(minutes=15):
        df = kb.resample(df, "15min")
        step = pd.Timedelta(minutes=15)
    tf_ms = int(step.total_seconds() * 1000)
    day_id = kb.make_day_ids(df.index, args.session_tz, args.session_hour)
    split = pd.Timestamp(args.split, tz=args.tz) if args.split else None

    if "cheap_max" not in {f.name for f in fields(kv.Config)}:
        print("NOTE: 'cheap_max' is not in your ktr_v4_backtest.py yet - apply the small patch first, "
              "otherwise runs that use it stop with 'Unknown setting'.\n")

    runs = []
    if args.preset:
        runs = [(nm, ov.split()) for nm, ov in PRESET]
    if args.grid:
        keys, vals = [], []
        for g in args.grid:
            k, v = g.split("=", 1)
            keys.append(k.strip())
            vals.append([x.strip() for x in v.split(",")])
        for combo in itertools.product(*vals):
            items = [f"{k}={v}" for k, v in zip(keys, combo)]
            runs.append((" ".join(items), items))
    if not runs:
        runs = [("settings from --set", [])]

    d0, d1 = df.index[0].tz_convert(args.tz), df.index[-1].tz_convert(args.tz)
    print(f"Data {d0:%Y-%m-%d} -> {d1:%Y-%m-%d} · " +
          (f"split {split:%Y-%m-%d} (A = before, B = from)" if split is not None else "no split (ALL only)"))
    hdr = f"{'setting':<58} │ {'A trades  win%   net R  DD R':<29} │ {'B trades  win%   net R  DD R':<29} │ {'ALL net R  DD R  months+':<24}"
    print(hdr)
    print("─" * len(hdr))
    for nm, items in runs:
        try:
            a, b, al = run_one(df, args.set, items, args, tf_ms, day_id, split)
        except SystemExit as e:
            print(f"{nm[:58]:<58} │ error: {e}")
            continue
        fa = f"{a['n']:>8} {a['wr']:5.1f}% {a['net']:+7.1f} {a['dd']:5.1f}"
        fb = f"{b['n']:>8} {b['wr']:5.1f}% {b['net']:+7.1f} {b['dd']:5.1f}"
        ok = "✅" if a["net"] > 0 and b["net"] > 0 else "  "
        print(f"{nm[:58]:<58} │ {fa:<29} │ {fb:<29} │ {al['net']:+8.1f} {al['dd']:5.1f}  {al['mo']:>6} {ok}")
    print("\n✅ = positive in BOTH periods. Prefer the line with the best A AND B, not the best ALL.")


if __name__ == "__main__":
    main()
