#!/usr/bin/env python3
"""Turn a TradingView "Export chart data" CSV into an AI training table.

The CSV must come from a chart with the "SMC 2026 ICT + KTR" indicator and its
"AI data columns" switch on (group ⓪d). Output: one row per KTR ❖ signal with
the features at the signal candle and the label of what happened to that trade.

    python3 ktr_ai_dataset.py export.csv                  -> export_dataset.csv
    python3 ktr_ai_dataset.py export.csv out.csv          -> out.csv
    python3 ktr_ai_dataset.py export.csv out.csv --all    -> also ❖ that were not taken

result column:
    WIN / LOSS   trade hit TP / SL
    MISSED       pending order cancelled before it filled (expired, ran away,
                 daily limit, session OFF, hedging rule)
    EARLY        closed early by an opposite ❖ (pts = what it made)
    OPEN         still running at the end of the export
    NOT TAKEN    ❖ skipped (only with --all): daily limit, session OFF,
                 prop limit, one-trade-at-a-time, hedging rule
"""
import csv
import math
import sys
from datetime import datetime, timezone

FEATURES = [
    "AI RSI7", "AI ATR14", "AI rel volume", "AI trend fast", "AI trend slow",
    "AI dist OP %", "AI dist 30MA ATR", "AI session", "AI boys vol %", "AI bullishness",
]
SESSIONS = {0: "Asia", 1: "London", 2: "New York", 3: "Other"}
CODES = {1: "WIN", -1: "LOSS", 0: "MISSED", 2: "EARLY"}


def num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    keep_all = "--all" in argv
    if not args:
        print(__doc__)
        return 1
    src = args[0]
    dst = args[1] if len(args) > 1 else src.rsplit(".", 1)[0] + "_dataset.csv"

    with open(src, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    head, data = rows[0], rows[1:]

    def col(name, required=True):
        # exact title first, then a title that ends with it (some exports add a prefix)
        for i, h in enumerate(head):
            if h.strip() == name:
                return i
        for i, h in enumerate(head):
            if h.strip().endswith(name):
                return i
        if required:
            sys.exit(f"column '{name}' not found — is 'AI data columns' on in the indicator (group ⓪d)?")
        return None

    c_time = 0
    c_ohlc = [col(n, False) for n in ("open", "high", "low", "close")]
    c_sig, c_taken = col("AI signal"), col("AI taken")
    c_en, c_tp, c_sl = col("AI entry"), col("AI TP"), col("AI SL")
    c_feat = [col(n) for n in FEATURES]
    c_res = [(col(f"AI res{k} bars ago"), col(f"AI res{k} code"), col(f"AI res{k} pts")) for k in (1, 2, 3)]

    def cell(row, c):
        return row[c] if c is not None and c < len(row) else ""

    # results are written on the candle where the trade ended → point them back at their ❖ row
    results = {}
    for i, row in enumerate(data):
        for c_ago, c_code, c_pts in c_res:
            ago = num(cell(row, c_ago))
            if ago is None:
                continue
            j = i - int(round(ago))
            if j >= 0:
                code = int(round(num(cell(row, c_code)) or 0))
                results[j] = (CODES.get(code, str(code)), num(cell(row, c_pts)) or 0.0, int(round(ago)))

    out_head = (["time", "time_utc", "open", "high", "low", "close", "direction", "taken", "entry", "tp", "sl"]
                + [n[3:].strip().replace(" ", "_").replace("%", "pct") for n in FEATURES]
                + ["session_name", "result", "pts", "candles_to_result"])
    out, counts = [], {}
    for i, row in enumerate(data):
        sig = num(cell(row, c_sig))
        if sig not in (1.0, -1.0):
            continue
        taken = (num(cell(row, c_taken)) or 0) > 0
        if not taken and not keep_all:
            continue
        t = cell(row, c_time)
        tn = num(t)
        t_utc = datetime.fromtimestamp(tn, tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if tn and tn > 1e9 else t
        if taken:
            res, pts, ago = results.get(i, ("OPEN", "", ""))
        else:
            res, pts, ago = "NOT TAKEN", "", ""
        ses = num(cell(row, c_feat[FEATURES.index("AI session")]))
        out.append([t, t_utc] + [cell(row, c) for c in c_ohlc]
                   + ["BUY" if sig > 0 else "SELL", int(taken),
                      cell(row, c_en), cell(row, c_tp), cell(row, c_sl)]
                   + [cell(row, c) for c in c_feat]
                   + [SESSIONS.get(int(ses), "") if ses is not None else "", res, pts, ago])
        counts[res] = counts.get(res, 0) + 1

    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(out_head)
        w.writerows(out)
    print(f"{len(out)} ❖ signals → {dst}")
    print("  " + " · ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
