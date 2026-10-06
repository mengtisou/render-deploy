#!/usr/bin/env python3
"""Turn a TradingView "Export chart data" CSV into an AI training table.

The CSV must come from a chart with the "SMC 2026 ICT + KTR" indicator (or the
"v3 + Export" version) and its "AI data columns" switch on. Output: one row per
KTR ❖ signal with the features at the signal candle and the label of what
happened to that trade.

    python3 ktr_ai_dataset.py export.csv                  -> export_dataset.csv
    python3 ktr_ai_dataset.py export.csv out.csv          -> out.csv
    python3 ktr_ai_dataset.py export.csv out.csv --all    -> also ❖ that were not taken

result column:
    WIN / LOSS   trade hit TP / SL
    MISSED       pending order cancelled before it filled (expired, ran away,
                 daily limit, session OFF, news window, hedging rule)
    EARLY        closed early (opposite ❖ or news window; pts = what it made)
    OPEN         still running at the end of the export
    NOT TAKEN    ❖ skipped (only with --all): daily limit, session OFF, news,
                 prop limit, one-trade-at-a-time, hedging rule

The indicator packs some values so it stays inside TradingView's 64 plot limit:
    AI signal     ±1 = ❖ taken · ±2 = ❖ not taken · 0 = no ❖
    AI trend      fast ±1 + slow ±2
    AI time code  session + 10 × (weekday + 1) + 100 × week of the month
    AI resN       bars back to the ❖ × 10 + (code + 2)   (code 1 / −1 / 0 / 2)
The older unpacked layout ("AI taken", "AI res1 bars ago" …) is read too.
"""
import csv
import math
import sys
from datetime import datetime, timezone

SESSIONS = {0: "Asia", 1: "London", 2: "New York", 3: "Other"}
NEWS = {0: "no news near", 1: "before news", 2: "news window", 3: "after news"}
WEEKDAYS = {-1: "Sat/Sun", 0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
CODES = {1: "WIN", -1: "LOSS", 0: "MISSED", 2: "EARLY"}
# AI columns that are not features (signal / order / results) — everything else starting with "AI " is a feature
CONTROL = ("AI signal", "AI taken", "AI entry", "AI TP", "AI SL")


def num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def clean(name):
    return name[3:].strip().replace(" ", "_").replace("%", "pct")


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
    head, data = [h.strip() for h in rows[0]], rows[1:]

    def col(name, required=True):
        # exact title first, then a title that ends with it (some exports add a prefix)
        for i, h in enumerate(head):
            if h == name:
                return i
        for i, h in enumerate(head):
            if h.endswith(name):
                return i
        if required:
            sys.exit(f"column '{name}' not found — is 'AI data columns' on in the indicator?")
        return None

    def cell(row, c):
        return row[c] if c is not None and c < len(row) else ""

    c_time = 0
    c_ohlc = [col(n, False) for n in ("open", "high", "low", "close")]
    c_sig = col("AI signal")
    c_taken = col("AI taken", False)                 # old layout only
    c_en, c_tp, c_sl = col("AI entry"), col("AI TP"), col("AI SL")
    c_boys = None if "AI boys vol %" in head else col("Boys", False)   # old layout already has it as a feature
    packed = "AI res1" in head
    if packed:
        c_res = [(col(f"AI res{k}"), None, col(f"AI res{k} pts")) for k in (1, 2, 3)]
    else:
        c_res = [(col(f"AI res{k} bars ago"), col(f"AI res{k} code"), col(f"AI res{k} pts")) for k in (1, 2, 3)]
    res_cols = {c for trio in c_res for c in trio if c is not None}
    feats = [(h, i) for i, h in enumerate(head)
             if h.startswith("AI ") and h not in CONTROL and i not in res_cols]

    # results are written on the candle where the trade ended → point them back at their ❖ row
    results = {}
    for i, row in enumerate(data):
        for c_a, c_c, c_p in c_res:
            v = num(cell(row, c_a))
            if v is None:
                continue
            if packed:
                ago = int(v // 10)
                code = int(round(v - ago * 10)) - 2
            else:
                ago = int(round(v))
                code = int(round(num(cell(row, c_c)) or 0))
            j = i - ago
            if j >= 0:
                results[j] = (CODES.get(code, str(code)), num(cell(row, c_p)) or 0.0, ago)

    names = [clean(h) for h, _ in feats]
    fset = {h for h, _ in feats}
    has_trend = "AI trend" in fset                               # packed: fast ±1 + slow ±2
    has_tcode = "AI time code" in fset                           # packed: session + weekday + week of month
    has_ses = not has_tcode and "AI session" in fset             # old layout
    has_wd = not has_tcode and "AI weekday" in fset              # old layout
    has_news = "AI news zone" in fset                            # v3 only
    extra = ((["trend_fast", "trend_slow"] if has_trend else [])
             + (["session", "session_name", "weekday", "weekday_name", "month_week"] if has_tcode else [])
             + (["session_name"] if has_ses else [])
             + (["news_zone_name"] if has_news else [])
             + (["weekday_name"] if has_wd else []))
    out_head = (["time", "time_utc", "open", "high", "low", "close", "direction", "taken", "entry", "tp", "sl"]
                + names + (["boys_vol_pct"] if c_boys is not None else []) + extra
                + ["result", "pts", "candles_to_result"])

    out, counts = [], {}
    for i, row in enumerate(data):
        sig = num(cell(row, c_sig))
        if sig is None or sig == 0:
            continue
        if c_taken is not None:
            taken = (num(cell(row, c_taken)) or 0) > 0
        else:
            taken = abs(sig) < 1.5
        if not taken and not keep_all:
            continue
        t = cell(row, c_time)
        tn = num(t)
        t_utc = datetime.fromtimestamp(tn, tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if tn and tn > 1e9 else t
        if taken:
            res, pts, ago = results.get(i, ("OPEN", "", ""))
        else:
            res, pts, ago = "NOT TAKEN", "", ""

        fv = {h: num(cell(row, c)) for h, c in feats}
        dec = []
        if has_trend:
            tr = fv.get("AI trend")
            if tr is None:
                dec += ["", ""]
            else:
                slow = 1 if tr in (1.0, 3.0) else -1     # fast ±1 + slow ±2 → 3, 1, −1, −3
                fast = int(tr - 2 * slow)
                dec += [fast, slow]
        if has_tcode:
            tc = fv.get("AI time code")
            if tc is None:
                dec += ["", "", "", "", ""]
            else:
                tc = int(round(tc))
                ses, wd, mw = tc % 10, (tc // 10) % 10 - 1, tc // 100
                dec += [ses, SESSIONS.get(ses, ""), wd, WEEKDAYS.get(wd, ""), mw]
        if has_ses:
            ses = fv.get("AI session")
            dec += [SESSIONS.get(int(ses), "") if ses is not None else ""]
        if has_news:
            nz = fv.get("AI news zone")
            dec += [NEWS.get(int(nz), "") if nz is not None else ""]
        if has_wd:
            wd = fv.get("AI weekday")
            dec += [WEEKDAYS.get(int(wd), "") if wd is not None else ""]

        out.append([t, t_utc] + [cell(row, c) for c in c_ohlc]
                   + ["BUY" if sig > 0 else "SELL", int(taken),
                      cell(row, c_en), cell(row, c_tp), cell(row, c_sl)]
                   + [cell(row, c) for _, c in feats]
                   + ([cell(row, c_boys)] if c_boys is not None else [])
                   + dec + [res, pts, ago])
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
