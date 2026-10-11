#!/usr/bin/env python3
"""
KTR v4  -  Python port of the Pine v6 "KTR v4" indicator's ❖ trades  (15-MINUTE CANDLES ONLY)
=================================================================================================
Replays the same rules as the TradingView script on ANY amount of history:
diamonds (reversal / continuation / micro) -> ❖ entry (+ volume, OP side, 1H/4H trend, wick,
order flow, ADX, cheap side, wait-1-candle filters) -> trade (at ❖ close, pending LIMIT / STOP with
expiry and run-away cancel) -> TP / SL with spread, London TP, break-even, daily limit, max ❖ per day,
sessions ON / OFF, 1 ❖ per session / wait after SL, skip after SL in a row, news filter
(auto NFP + your list), weekend rule. It prints the same numbers as the Pine Logs "KTR v4 SUMMARY",
plus every trade.

Defaults = the KTR v4 Pine defaults found with the 2-year test: London off, continuation ◇ off,
1H trend filter on, ADX / wick filters off (max ❖ per day and cheap side are new, default off).

Needs ktr_backtest.py in the same folder (data loader + indicator maths are shared).

Quick start
-----------
    python export_mt5_5m.py --tf M15                 # 15-minute candles from MT5 -> XAUUSD_15m.csv
    python ktr_v4_backtest.py XAUUSD_15m.csv
    python ktr_v4_backtest.py XAUUSD_5m.csv          # 1m / 5m files are turned into 15m candles automatically
    python ktr_v4_backtest.py XAUUSD_15m.csv --set max_day=2
    python ktr_v4_backtest.py XAUUSD_15m.csv --set cheap_max=1
    python ktr_v4_backtest.py XAUUSD_15m.csv --set entry=close --set day_on=false
    python ktr_v4_backtest.py --show-settings        # every setting (same defaults as the Pine inputs)
    python ktr_v4_backtest.py --demo                 # synthetic data, only to see it run

Not ported (default OFF in Pine): prop firm mode (and its hedging rule) and "Entry ❖ confirm on lower TF".
Display-only parts (lines, labels, alerts, colours, the pane) are not needed for the numbers.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass, field, fields

import numpy as np
import pandas as pd

try:
    import ktr_backtest as kb
except ImportError:
    sys.exit("ktr_backtest.py must be in the same folder as ktr_v4_backtest.py (it has the data loader and indicator maths).")

NAN = float("nan")
SPREADS = [0.0, 0.18, 0.22, 0.30]          # the four spreads the Pine dashboard compares
SES_NM = ["Asia", "London", "New York", "Other"]
WD_NM = ["Mon", "Tue", "Wed", "Thu", "Fri"]
MO_NM = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
NEWS_DEFAULT = """2026-07-14 08:30 | CPI
2026-07-29 14:00 | FOMC
2026-07-29 14:30 | FOMC presser
2026-09-11 08:30 | CPI
2026-09-16 14:00 | FOMC
2026-09-16 14:30 | FOMC presser
2026-10-14 08:30 | CPI
2026-10-28 14:00 | FOMC
2026-10-28 14:30 | FOMC presser
2026-10-29 08:30 | GDP + PCE
2026-11-10 08:30 | CPI
2026-12-09 14:00 | FOMC
2026-12-09 14:30 | FOMC presser
2026-12-10 08:30 | CPI"""


# ═════════════════════════════════════════════════════════════════════════════
#  SETTINGS  (Pine input defaults; change with --set key=value)
# ═════════════════════════════════════════════════════════════════════════════
@dataclass
class Config:
    # ⓪ KTR module / diamonds
    step_pct: float = 0.40
    st_f: float = 2.0              # Supertrend factor
    st_a: int = 10                 # Supertrend ATR length
    rsi_on: bool = True
    rsi_lo: float = 35.0
    rsi_hi: float = 65.0
    cool: int = 3                  # min bars between alerts
    win: int = 12                  # ❖ confirm window (bars)
    t_rev: bool = True             # trade ❖ from REVERSAL diamonds
    t_con: bool = False            # … CONTINUATION
    t_mic: bool = True             # … MICRO-PULLBACK
    cont: bool = True              # continuation signals (trend pullbacks)
    vol_on: bool = True            # ❖ needs above-average volume
    vol_m: float = 1.0
    op_filter: str = "off"         # off | entries | all   (OP side filter)
    htf: str = "1h"                # off | 1h | 4h        (❖ only with the higher-TF trend)
    wick: bool = False             # skip ❖ on a rejection candle
    wick_pct: float = 40.0
    hold: bool = False             # wait 1 candle: next candle must hold
    of_on: bool = False            # ❖ needs order flow on its side
    of_min: float = 10.0
    of_len: int = 10               # order flow delta lookback (⑨ Display)
    adx_on: bool = False           # no ❖ against a strong one-way trend
    adx_min: float = 30.0
    cheap_max: float = 0.0         # 0 = off · skip ❖ more than N KTR steps on the cheap side of OP
    # ⓪b ❖ trades
    entry: str = "limit"           # close | limit | stop
    off: float = 20.0              # pending offset (pts)
    exp: int = 10                  # pending expires after N candles
    run: int = 200                 # pending also cancelled when price runs: 0 (candles only) | 100 | 200
    tp: float = 200.0
    tp_lon: float = 0.0            # London TP (0 = same as TP)
    sl: float = 100.0
    pt: float = 0.10               # 1 point = price
    one: bool = False              # one trade at a time
    both: str = "Loss"             # TP and SL on the same candle
    spread: float = 0.22           # 0 | 0.18 | 0.22 | 0.30
    spread_cmp: bool = True        # also run every spread (dashboard rows)
    ses_asia_on: bool = True
    ses_asia: str = "0000-0700"
    ses_lon_on: bool = False
    ses_lon: str = "0700-1200"
    ses_ny_on: bool = True
    ses_ny: str = "1200-2100"
    ses_other_on: bool = True
    ses_tz: str = "UTC"
    ses_lim: str = "off"           # off | one (1 ❖ trade per session) | slwait (after an SL wait for the next session)
    day_on: bool = True            # daily limit
    day_tp: float = 400.0
    day_sl: float = 300.0
    max_day: int = 0               # 0 = no limit · max ❖ trades / orders per trading day
    lot_on: bool = True            # lot test
    lot_base: float = 0.01
    lot_step: float = 0.02
    lot_max: float = 0.03
    be_on: bool = False            # break-even
    be_pts: float = 100.0
    be_lock: float = 0.0
    sk_on: bool = False            # skip ❖ after SL in a row
    sk_n: int = 2
    sk_m: int = 1
    sk_day: bool = True
    # ⓪d news filter
    news_on: bool = True
    news_bef: int = 45
    news_aft: int = 15
    news_sp: int = 10              # speeches: minutes before AND after (0 = same as news)
    news_act: str = "cancel"       # cancel (pending only) | close (also close open trades)
    nfp: bool = True
    news_tz: str = "America/New_York"
    news_pre_len: int = 180        # stats: 'before news' zone
    news_post_len: int = 120       # stats: 'after news' zone
    # ⓪h weekend rule
    we_on: bool = True
    we_min: int = 120
    we_tz: str = "America/New_York"
    we_h: int = 17
    we_m: int = 0
    we_reopen: int = 0
    rep_on: bool = True            # 🔬 filter report


CHOICES = {"op_filter": {"off", "entries", "all"}, "htf": {"off", "1h", "4h"}, "entry": {"close", "limit", "stop"},
           "run": {0, 100, 200}, "both": {"Loss", "Win"}, "spread": set(SPREADS), "ses_lim": {"off", "one", "slwait"},
           "news_act": {"cancel", "close"}}


def apply_overrides(cfg: Config, items):
    for it in items or []:
        if "=" not in it:
            sys.exit(f"--set expects key=value, got '{it}'")
        k, v = (s.strip() for s in it.split("=", 1))
        if not hasattr(cfg, k):
            sys.exit(f"Unknown setting '{k}'. Run with --show-settings to see the list.")
        cur = getattr(cfg, k)
        if isinstance(cur, bool):
            val = v.lower() in ("1", "true", "yes", "on", "y")
        elif isinstance(cur, int):
            val = int(v)
        elif isinstance(cur, float):
            val = float(v)
        else:
            val = v
        setattr(cfg, k, val)
    for k, allowed in CHOICES.items():
        if getattr(cfg, k) not in allowed:
            sys.exit(f"Setting {k} must be one of {sorted(allowed, key=str)}")


# ═════════════════════════════════════════════════════════════════════════════
#  INDICATORS + TIME TABLES
# ═════════════════════════════════════════════════════════════════════════════
def htf_dir(df, cfg, hours, anchor_tz, anchor_hour):
    """request.security(…, f_htfDir()) = Supertrend direction of the LAST CLOSED 1H / 4H candle."""
    idx = df.index
    if hours == 1:
        key = idx.floor("1h")
    else:                                            # 4H candles counted from the trading-day start
        key = (idx.tz_convert(anchor_tz).tz_localize(None) - pd.Timedelta(hours=anchor_hour)).floor(f"{hours}h")
    g = df.groupby(key, sort=True).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    h, l, c = (g[k].to_numpy(float) for k in ("high", "low", "close"))
    with np.errstate(all="ignore"):
        d = kb.supertrend_dir(h, l, c, cfg.st_f, kb.rma(kb.true_range(h, l, c), cfg.st_a))
    prev = pd.Series(np.r_[NAN, d[:-1]], index=g.index)
    return prev.reindex(key).to_numpy()


def indicators(df, cfg, sess_tz, sess_hour):
    h, l, c, o, v = (df[k].to_numpy(float) for k in ("high", "low", "close", "open", "volume"))
    with np.errstate(all="ignore"):
        atr = kb.rma(kb.true_range(h, l, c), cfg.st_a)
        up = kb.supertrend_dir(h, l, c, cfg.st_f, atr) < 0
        slow = kb.supertrend_dir(h, l, c, cfg.st_f * 2.0, atr) < 0
        r7 = pd.Series(kb.rsi(c, 7))
        dip, dim, adx = kb.dmi(h, l, c, 14)
        rel = v / pd.Series(v).rolling(20).mean().to_numpy()
        rng = np.maximum(h - l, 0.0001)
        bv = np.where(c >= o, v, v * (c - l) / rng)
        sv = np.where(c < o, v, v * (h - c) / rng)
        s1 = pd.Series(bv - sv).rolling(cfg.of_len).sum().to_numpy()
        s2 = pd.Series(bv + sv).rolling(cfg.of_len).sum().to_numpy()
        ofd = s1 / np.maximum(s2, 0.0001) * 100
        low12 = pd.Series(l).rolling(12).min().to_numpy()
        high12 = pd.Series(h).rolling(12).max().to_numpy()
        hdir = htf_dir(df, cfg, 4 if cfg.htf == "4h" else 1, sess_tz, sess_hour)
    return dict(up=up.tolist(), slow=slow.tolist(),
                lo5=r7.rolling(5).min().tolist(), hi5=r7.rolling(5).max().tolist(),
                at_low=(kb.bars_since(l == low12) <= 3).tolist(), at_high=(kb.bars_since(h == high12) <= 3).tolist(),
                dip=dip.tolist(), dim=dim.tolist(), adx=adx.tolist(), rel=rel.tolist(), ofd=ofd.tolist(), hdir=hdir.tolist())


def parse_events(text, tz, kind):
    """Pine f_nwParse: 'YYYY-MM-DD HH:MM | name' per line; // and # lines ignored."""
    out = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if len(s) < 16 or s.startswith("//") or s.startswith("#"):
            continue
        try:
            ts = pd.Timestamp(year=int(s[0:4]), month=int(s[5:7]), day=int(s[8:10]), hour=int(s[11:13]),
                              minute=int(s[14:16]), tz=tz)
        except ValueError:
            continue
        lab = s[16:].strip().lstrip("|").strip()
        out.append((int(ts.value // 10**6), kind, lab or ("Speech" if kind else "News")))
    return out


def nfp_events(idx):
    """First Friday of every month, 08:30 New York (Pine f_nfpEv)."""
    out = []
    ny = idx.tz_convert("America/New_York")
    for per in pd.period_range(ny[0].strftime("%Y-%m"), ny[-1].strftime("%Y-%m"), freq="M"):
        d = pd.Timestamp(year=per.year, month=per.month, day=1)
        d += pd.Timedelta(days=(4 - d.dayofweek) % 7)
        ts = pd.Timestamp(year=d.year, month=d.month, day=d.day, hour=8, minute=30, tz="America/New_York")
        out.append((int(ts.value // 10**6), 0, "NFP (auto)"))
    return out


def news_zone(t0, t1, events, cfg):
    """Pine f_nwZone for candles [t0, t1): 0 normal · 1 before · 2 window · 3 after (window beats after beats before)."""
    pre_n, post_n = cfg.news_bef * 60000, cfg.news_aft * 60000
    bef_z, aft_z = cfg.news_pre_len * 60000, cfg.news_post_len * 60000
    tl = t1 - 1
    best = np.zeros(len(t0), dtype=np.int64)
    for ev, kind, _ in events:
        pre = cfg.news_sp * 60000 if kind == 1 and cfg.news_sp > 0 else pre_n
        post = cfg.news_sp * 60000 if kind == 1 and cfg.news_sp > 0 else post_n
        ns, ne = ev - pre, ev + post
        lo, hi = np.searchsorted(tl, ns - bef_z - 1), np.searchsorted(t0, ne + aft_z + 1)
        if lo >= hi:
            continue
        a0, a1, al = t0[lo:hi], t1[lo:hi], tl[lo:hi]
        win = (ns < a1) & (ne > a0)
        aft = ~win & (al >= ne) & (al < ne + aft_z)
        bef = ~win & ~aft & (al >= ns - bef_z) & (al < ns)
        best[lo:hi] = np.maximum(best[lo:hi], np.where(win, 3, np.where(aft, 2, np.where(bef, 1, 0))))
    return np.select([best == 3, best == 2, best == 1], [2, 3, 1], 0)


def weekend_block(ts_ms, idx_like, cfg, last_gap):
    """Pine f_weBlkAt: Friday from (close − N min), Saturday, and the optional minutes after the reopen."""
    if not cfg.we_on:
        return np.zeros(len(ts_ms), bool)
    loc = idx_like.tz_convert(cfg.we_tz)
    mins = loc.hour * 60 + loc.minute
    b = ((loc.dayofweek == 4) & (mins >= cfg.we_h * 60 + cfg.we_m - cfg.we_min)) | (loc.dayofweek == 5)
    b = np.asarray(b)
    if cfg.we_reopen > 0:
        b |= ~np.isnan(last_gap) & (ts_ms >= last_gap) & (ts_ms < last_gap + cfg.we_reopen * 60000)
    return b


def in_session(idx, sess, tz):
    loc = idx.tz_convert(tz)
    m = np.asarray(loc.hour * 60 + loc.minute)
    a = int(sess[0:2]) * 60 + int(sess[2:4])
    b = int(sess[5:7]) * 60 + int(sess[7:9])
    return (m >= a) & (m < b) if a < b else (m >= a) | (m < b)


# ═════════════════════════════════════════════════════════════════════════════
#  SIMULATION
# ═════════════════════════════════════════════════════════════════════════════
@dataclass
class Tr:
    d: int
    en: float
    tp: float
    sl: float
    bar: int
    filled: bool
    lim: bool
    sig: int
    sc: int
    ses: int
    wd: int
    nws: int
    mw: int
    ses_id: int
    tp_pts: float
    name: str
    nth: int = 0
    tid: int = -1
    be: bool = False
    lot: float = NAN


@dataclass
class St:
    spr: float
    wins: int = 0
    losses: int = 0
    winB: int = 0
    lossB: int = 0
    winS: int = 0
    lossS: int = 0
    missed: int = 0
    skipDay: int = 0
    nOpen: int = 0
    net: float = 0.0
    dayPts: float = 0.0
    dayW: int = 0
    dayL: int = 0
    dayStop: bool = False
    dayWhy: str = ""
    daysTgt: int = 0
    daysLoss: int = 0
    sesSkip: int = 0
    early: int = 0
    earlyPts: float = 0.0
    nwSkip: int = 0
    beN: int = 0
    bePts: float = 0.0
    lRun: int = 0
    skLeft: int = 0
    skN: int = 0
    sesTrId: int = -1
    sesSlId: int = -1
    sesLimSk: int = 0
    weSkip: int = 0
    day_n: int = 0             # ❖ trades / orders placed today (max per day)
    maxSkip: int = 0           # ❖ skipped by 'max ❖ per day'


class Main:
    """Everything the Pine script only counts for the picked spread (●)."""
    def __init__(self):
        z = lambda k, x=0: [x] * k
        self.sesW, self.sesL, self.sesWB, self.sesLB, self.sesPts, self.sesSkip, self.sesLimSk = z(4), z(4), z(4), z(4), z(4, 0.0), z(4), z(4)
        self.wdW, self.wdL, self.wdWB, self.wdLB, self.wdPts, self.wdCnt = z(5), z(5), z(5), z(5), z(5, 0.0), z(5)
        self.wdOut = 0
        self.mwW, self.mwL, self.mwPts, self.mwCnt, self.mwTgt, self.mwLoss = z(5), z(5), z(5, 0.0), z(5), z(5), z(5)
        self.wdTgt, self.wdLoss = z(5), z(5)
        self.nwW, self.nwL, self.nwWB, self.nwLB, self.nwPts = z(4), z(4), z(4), z(4), z(4, 0.0)
        self.nthW, self.nthL, self.nthM, self.nthE, self.nthPts = z(4), z(4), z(4), z(4), z(4, 0.0)
        self.tr = []          # per ❖: dict(day, nth, prev, code, pts, typ, dir, ses, htf, of, adx, loc)
        self.mo = {}          # month index -> [W, L, E, pts, lot$, days, 🎯, ⛔]
        self.lot = [0.0, 0.0, 0.0, 0.0]   # $ result, peak, max DD, biggest lot
        self.rows = []        # closed trades for the CSV
        self.tlog = []        # every ❖ trade like the Pine 'V4T' log: (live bar, order, entry, result, exit bar)


def simulate(df, cfg, day_id, tf_ms, sess_tz, sess_hour):
    ind = indicators(df, cfg, sess_tz, sess_hour)
    o, h, l, c = (df[k].tolist() for k in ("open", "high", "low", "close"))
    n = len(o)
    idx = df.index
    t_ms = ((idx - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)).to_numpy().astype(np.int64)   # unit-safe
    tc_ms = t_ms + tf_ms
    idx_c = idx + pd.Timedelta(milliseconds=tf_ms)

    # time tables (session, weekday, week of month, month, news, weekend) - computed once
    ses_on = [cfg.ses_asia_on, cfg.ses_lon_on, cfg.ses_ny_on, cfg.ses_other_on]
    a_, l_, n_ = (in_session(idx, s, cfg.ses_tz) for s in (cfg.ses_asia, cfg.ses_lon, cfg.ses_ny))
    ses_now = np.where(n_, 2, np.where(l_, 1, np.where(a_, 0, 3))).tolist()
    sloc = idx.tz_convert(cfg.ses_tz)
    dow = np.asarray(sloc.dayofweek)
    wd_now = np.where(dow <= 4, dow, -1).tolist()
    mw_now = np.minimum((np.asarray(sloc.day) - 1) // 7, 3).tolist()
    mo_now = (np.asarray(sloc.year) * 12 + np.asarray(sloc.month) - 1).tolist()
    events = parse_events(NEWS_TEXT, cfg.news_tz, 0) + parse_events(SPEECH_TEXT, cfg.news_tz, 1)
    if cfg.nfp:
        events += nfp_events(idx)
    events.sort()
    nw_bar = news_zone(t_ms, tc_ms, events, cfg)
    nw_place = news_zone(tc_ms, tc_ms + 1, events, cfg)
    nw_bar_l, nw_place_l = nw_bar.tolist(), nw_place.tolist()
    gap = np.r_[False, np.diff(t_ms) > 43200000] & (tf_ms < 43200000)
    last_gap = pd.Series(np.where(gap, t_ms, np.nan)).ffill().to_numpy()
    we_blk = weekend_block(t_ms, idx, cfg, last_gap).tolist()
    we_place = weekend_block(tc_ms, idx_c, cfg, last_gap).tolist()
    gap_l = gap.tolist()

    up_a, slow_a, lo5, hi5 = ind["up"], ind["slow"], ind["lo5"], ind["hi5"]
    at_low, at_high, dip, dim, adx = ind["at_low"], ind["at_high"], ind["dip"], ind["dim"], ind["adx"]
    rel, ofd, hdir = ind["rel"], ind["ofd"], ind["hdir"]

    sel = SPREADS.index(cfg.spread)
    scen = [s for s in range(4) if s == sel or cfg.spread_cmp]
    st = [St(spr=s) for s in SPREADS]
    M = Main()
    opn: list = []
    pend = cfg.entry != "close"
    lim = cfg.entry == "limit"
    run_d = cfg.run * cfg.pt if cfg.run else NAN
    off_d, sl_d = cfg.off * cfg.pt, cfg.sl * cfg.pt
    ses1, ses_slw = cfg.ses_lim == "one", cfg.ses_lim == "slwait"
    nw_close_on = cfg.news_on and cfg.news_act == "close"

    # state
    op = NAN
    last_sig = -99999
    buy_bar = sell_bar = -99999
    buy_hi = sell_lo = NAN
    buy_done = sell_done = True
    buy_type = sell_type = 0
    u_buy_done = u_sell_done = True
    up_run = dn_run = 0
    prev_sig_b = prev_sig_s = False
    ses_id = 0
    day_id_ctr = 0
    nth_day = 0
    lot = cfg.lot_base
    prev_day = 0
    first_tm = None
    days_all = 0
    pk = dd = 0.0
    shadows: list = []                          # 🔬 [dir, entry, set, mask, from_bar]
    rep_w, rep_l, rep_p = [0, 0, 0], [0, 0, 0], [0.0, 0.0, 0.0]
    rep_fw, rep_fl, rep_fn = [0] * 4, [0] * 4, [0] * 4
    i = 0

    def mo_slot():
        return M.mo.setdefault(mo_now[i], [0, 0, 0, 0.0, 0.0, 0, 0, 0])

    def nth_rec(t, code, pts):
        if cfg.lot_on and t.lot == t.lot and code != 0:
            b = M.lot[0] + pts * cfg.pt * 100 * t.lot
            M.lot[0] = b
            M.lot[1] = max(M.lot[1], b)
            M.lot[2] = max(M.lot[2], M.lot[1] - b)
        if t.tid >= 0:
            s = min(t.nth, 4) - 1
            if code == 1:
                M.nthW[s] += 1
            elif code == -1:
                M.nthL[s] += 1
            elif code == 0:
                M.nthM[s] += 1
            else:
                M.nthE[s] += 1
            M.nthPts[s] += pts
            M.tr[t.tid]["code"], M.tr[t.tid]["pts"] = code, pts

    def mo_rec(t, code, pts):
        m = mo_slot()
        m[0 if code == 1 else 1 if code == -1 else 2] += 1
        m[3] += pts
        if cfg.lot_on and t.lot == t.lot:
            m[4] += pts * cfg.pt * 100 * t.lot

    def log_row(t, res, pts, px):
        M.rows.append((t.sig, t.bar, i, t.name, t.en, t.tp, t.sl, res, pts, SES_NM[t.ses], t.nth, t.lot, px))
        M.tlog.append((t.bar, t.name, t.en, res if res in ("WIN", "LOSS") else f"CLOSED {rnd(pts):+d}", i))

    def day_check(s, main):
        if cfg.day_on and not s.dayStop and (s.dayPts >= cfg.day_tp or s.dayPts <= -cfg.day_sl):
            tgt = s.dayPts >= cfg.day_tp
            s.dayStop = True
            s.daysTgt += tgt
            s.daysLoss += not tgt
            s.dayWhy = "🎯 target hit" if tgt else "⛔ loss limit"
            if main:
                (M.mwTgt if tgt else M.mwLoss)[mw_now[i]] += 1
                if wd_now[i] >= 0:
                    (M.wdTgt if tgt else M.wdLoss)[wd_now[i]] += 1
                mo_slot()[6 if tgt else 7] += 1

    def close_now(t, s, base, why):
        px = base if t.d == 1 else base + s.spr
        pts = t.d * (px - t.en) / cfg.pt
        s.early += 1
        s.earlyPts += pts
        if t.sc == sel:
            nth_rec(t, 2, pts)
            mo_rec(t, 2, pts)
            M.sesPts[t.ses] += pts
            if t.wd >= 0:
                M.wdPts[t.wd] += pts
            M.nwPts[t.nws] += pts
            M.mwPts[t.mw] += pts
            log_row(t, "CLOSED (" + why + ")", pts, px)
        s.net += pts
        s.dayPts += pts
        s.nOpen -= 1

    def cancel(t):
        s = st[t.sc]
        if t.sc == sel:
            M.tlog.append((t.bar, t.name, t.en, "CANCEL", i))
        if s.sesTrId == t.ses_id:
            s.sesTrId = -1
        if t.sc == sel:
            nth_rec(t, 0, 0.0)

    def flow_ok(d):
        x = ofd[i]
        of_ok = (not cfg.of_on) or x != x or (x >= cfg.of_min if d == 1 else x <= -cfg.of_min)
        adx_ok = not (cfg.adx_on and adx[i] >= cfg.adx_min) or (dip[i] >= dim[i] if d == 1 else dim[i] >= dip[i])
        return of_ok and adx_ok

    def wick_ok(d):
        rng = h[i] - l[i]
        return (not cfg.wick) or rng <= 0 or ((h[i] - c[i]) if d == 1 else (c[i] - l[i])) <= rng * cfg.wick_pct / 100

    for i in range(n):
        oi, hi, li, ci = o[i], h[i], l[i], c[i]
        new_day = i > 0 and day_id[i] != day_id[i - 1]
        if new_day:
            op = oi
        have_op = op == op
        stp = op * cfg.step_pct / 100.0 if have_op else NAN

        # ── stage 1: diamonds ──
        up, slow = up_a[i], slow_a[i]
        prev_up = up_a[i - 1] if i > 0 else False
        bull = i > 0 and ci > oi and ci > h[i - 1]
        bear = i > 0 and ci < oi and ci < l[i - 1]
        rev_b = (not up) and bull and ((not cfg.rsi_on) or lo5[i] <= cfg.rsi_lo or at_low[i])
        rev_s = up and bear and ((not cfg.rsi_on) or hi5[i] >= cfg.rsi_hi or at_high[i])
        con_b = cfg.cont and slow and (not up) and bull and ((not cfg.rsi_on) or lo5[i] <= 45)
        con_s = cfg.cont and (not slow) and up and bear and ((not cfg.rsi_on) or hi5[i] >= 55)
        mic_s = cfg.cont and (not slow) and (not up) and up_run >= 2 and bear
        mic_b = cfg.cont and slow and up and dn_run >= 2 and bull
        up_run = up_run + 1 if ci > oi else 0
        dn_run = dn_run + 1 if ci < oi else 0
        op_on, op_dia = cfg.op_filter != "off", cfg.op_filter == "all"
        op_b_ok = (not op_on) or (not have_op) or ci > op
        op_s_ok = (not op_on) or (not have_op) or ci < op
        cool_ok = i - last_sig >= cfg.cool
        al_b = (rev_b or con_b or mic_b) and cool_ok and ((not op_dia) or op_b_ok)
        al_s = (rev_s or con_s or mic_s) and cool_ok and ((not op_dia) or op_s_ok)
        if al_b or al_s:
            last_sig = i
        if al_b:
            buy_bar, buy_hi, buy_done = i, hi, False
            buy_type = 0 if rev_b else 1 if con_b else 2
            u_buy_done = False
        if al_s:
            sell_bar, sell_lo, sell_done = i, li, False
            sell_type = 0 if rev_s else 1 if con_s else 2
            u_sell_done = False
        type_ok = [cfg.t_rev, cfg.t_con, cfg.t_mic]

        # ── stage 2: ❖ entry + filters ──
        flip_up = up and not prev_up
        flip_dn = (not up) and prev_up
        vol_ok = (not cfg.vol_on) or rel[i] >= cfg.vol_m
        hd = hdir[i]
        htf_b_ok = cfg.htf == "off" or hd != hd or hd < 0
        htf_s_ok = cfg.htf == "off" or hd != hd or hd > 0
        wk_b, wk_s = wick_ok(1), wick_ok(-1)
        fl_b, fl_s = flow_ok(1), flow_ok(-1)
        # cheap side: BUY far below OP / SELL far above OP (more than cheap_max KTR steps) is skipped
        loc_x = (ci - op) / stp if (have_op and stp == stp and stp > 0) else NAN
        chp_b = cfg.cheap_max <= 0 or loc_x != loc_x or -loc_x <= cfg.cheap_max
        chp_s = cfg.cheap_max <= 0 or loc_x != loc_x or loc_x <= cfg.cheap_max
        sig_b = ((not buy_done) and i - buy_bar <= cfg.win and vol_ok and op_b_ok and htf_b_ok and wk_b and fl_b and
                 chp_b and type_ok[buy_type] and (flip_up or (i > buy_bar and ci > buy_hi)))
        sig_s = ((not sell_done) and i - sell_bar <= cfg.win and vol_ok and op_s_ok and htf_s_ok and wk_s and fl_s and
                 chp_s and type_ok[sell_type] and (flip_dn or (i > sell_bar and ci < sell_lo)))
        if sig_b:
            buy_done = True
        if sig_s:
            sell_done = True
        if cfg.hold:
            ent_b = prev_sig_b and ci > (h[i - 1] + l[i - 1]) / 2
            ent_s = prev_sig_s and ci < (h[i - 1] + l[i - 1]) / 2
        else:
            ent_b, ent_s = sig_b, sig_s

        # ── 🔬 filter report: v3 ❖ (no filters) + one simple trade test ──
        u_b = (not u_buy_done) and i - buy_bar <= cfg.win and vol_ok and op_b_ok and (flip_up or (i > buy_bar and ci > buy_hi))
        u_s = (not u_sell_done) and i - sell_bar <= cfg.win and vol_ok and op_s_ok and (flip_dn or (i > sell_bar and ci < sell_lo))
        if u_b:
            u_buy_done = True
        if u_s:
            u_sell_done = True
        if cfg.rep_on:
            def sh_add(d, base, sset, mk, frm):
                shadows.append([d, base + cfg.spread if d == 1 else base, sset, mk, frm])
                if sset == 2:
                    for k in range(4):
                        if mk >> k & 1:
                            rep_fn[k] += 1

            def mask(d):
                return ((not (htf_b_ok if d == 1 else htf_s_ok)) * 1 + (not (wk_b if d == 1 else wk_s)) * 2 +
                        (not ((fl_b and chp_b) if d == 1 else (fl_s and chp_s))) * 4)
            if u_b:
                sh_add(1, ci, 0, 0, i + 1)
                if not sig_b:
                    sh_add(1, ci, 2, mask(1), i + 1)
            if u_s:
                sh_add(-1, ci, 0, 0, i + 1)
                if not sig_s:
                    sh_add(-1, ci, 2, mask(-1), i + 1)
            if ent_b:
                sh_add(1, ci, 1, 0, i + 1)
            if ent_s:
                sh_add(-1, ci, 1, 0, i + 1)
            if cfg.hold and prev_sig_b and not ent_b:
                sh_add(1, c[i - 1], 2, 8, i)
            if cfg.hold and prev_sig_s and not ent_s:
                sh_add(-1, c[i - 1], 2, 8, i)
            keep = []
            tpd, sld = cfg.tp * cfg.pt, cfg.sl * cfg.pt
            for sh in reversed(shadows):
                d, en, sset, mk, frm = sh
                if i >= frm:
                    xh = hi if d == 1 else hi + cfg.spread
                    xl = li if d == 1 else li + cfg.spread
                    htp = xh >= en + tpd if d == 1 else xl <= en - tpd
                    hsl = xl <= en - sld if d == 1 else xh >= en + sld
                    if htp or hsl:
                        w = htp and ((not hsl) or cfg.both == "Win")
                        rep_w[sset] += w
                        rep_l[sset] += not w
                        rep_p[sset] += cfg.tp if w else -cfg.sl
                        if sset == 2:
                            for k in range(4):
                                if mk >> k & 1:
                                    rep_fw[k] += w
                                    rep_fl[k] += not w
                        continue
                keep.append(sh)
            shadows = keep[::-1]
        prev_sig_b, prev_sig_s = sig_b, sig_s

        # ── session id, new trading day ──
        if (i > 0 and ses_now[i] != ses_now[i - 1]) or new_day:
            ses_id += 1
        ses_ok_now = ses_on[ses_now[i]]
        if new_day:
            why = st[sel].dayWhy
            prev_day = 1 if why == "⛔ loss limit" else 2 if why == "🎯 target hit" else 0
            lot = min(round(lot + cfg.lot_step, 2), cfg.lot_max) if prev_day == 1 else cfg.lot_base if prev_day == 2 else lot
            day_id_ctr += 1
            nth_day = 0
            for s in st:
                s.dayPts, s.dayW, s.dayL, s.dayStop, s.dayWhy = 0.0, 0, 0, False, ""
                s.day_n = 0
                if cfg.sk_day:
                    s.lRun = s.skLeft = 0
            if first_tm is not None:
                days_all += 1
        if first_tm is not None:
            if i > 0 and dow[i] != dow[i - 1] and wd_now[i] >= 0:
                M.wdCnt[wd_now[i]] += 1
            if i > 0 and mw_now[i] != mw_now[i - 1]:
                M.mwCnt[mw_now[i]] += 1
            if new_day:
                mo_slot()[5] += 1

        nw_blk = cfg.news_on and nw_bar_l[i] == 2
        nw_start = nw_bar_l[i] == 2 and (i == 0 or nw_bar_l[i - 1] != 2)
        nw_close = nw_close_on and nw_start
        we_start = we_blk[i] and (i == 0 or not we_blk[i - 1])
        we_close = cfg.we_on and (we_start or gap_l[i])
        we_cx = we_blk[i] or (cfg.we_on and gap_l[i])

        # ── 1) settle pending orders and open trades (newest first, like the Pine loop) ──
        for k in range(len(opn) - 1, -1, -1):
            t = opn[k]
            s = st[t.sc]
            main = t.sc == sel
            sp = s.spr
            done = fill_now = False
            e_hi, e_lo = (hi + sp, li + sp) if t.d == 1 else (hi, li)
            x_hi, x_lo, x_cl = (hi, li, ci) if t.d == 1 else (hi + sp, li + sp, ci + sp)
            if (nw_close or we_close) and t.filled:
                close_now(t, s, oi, "weekend rule" if we_close else "news window")
                day_check(s, main)
                del opn[k]
                continue
            fill_dn = (t.d == 1) == t.lim
            if not t.filled and i > t.sig:
                touch = e_lo <= t.en if fill_dn else e_hi >= t.en
                ran = run_d == run_d and (e_hi >= t.en + run_d if fill_dn else e_lo <= t.en - run_d)
                if nw_blk:
                    done = True
                    s.nwSkip += 1
                    s.nOpen -= 1
                    cancel(t)
                    del opn[k]
                elif we_cx:
                    done = True
                    s.weSkip += 1
                    s.nOpen -= 1
                    cancel(t)
                    del opn[k]
                elif touch and not ses_ok_now:
                    done = True
                    s.sesSkip += 1
                    s.nOpen -= 1
                    if main:
                        M.sesSkip[ses_now[i]] += 1
                    cancel(t)
                    del opn[k]
                elif touch:
                    t.filled = True
                    t.ses, t.wd, t.nws, t.mw, t.bar = ses_now[i], wd_now[i], nw_bar_l[i], mw_now[i], i
                    fill_now = True
                elif ran or i - t.sig >= cfg.exp:
                    done = True
                    s.missed += 1
                    s.nOpen -= 1
                    cancel(t)
                    del opn[k]
            if t.filled and not done and (i > t.bar or fill_now):
                # fill candle: only what surely came after the fill (filled on the way down -> its high is not sure)
                a_hi = x_cl if fill_now and fill_dn else x_hi
                a_lo = x_cl if fill_now and not fill_dn else x_lo
                hit_tp = a_hi >= t.tp if t.d == 1 else a_lo <= t.tp
                hit_sl = a_lo <= t.sl if t.d == 1 else a_hi >= t.sl
                if t.be and hit_sl and not (hit_tp and cfg.both == "Win"):
                    s.beN += 1
                    s.bePts += t.d * (t.sl - t.en) / cfg.pt
                    close_now(t, s, t.sl if t.d == 1 else t.sl - sp, "break-even")
                    day_check(s, main)
                    del opn[k]
                    done = True
                    hit_tp = hit_sl = False
                if hit_tp or hit_sl:
                    win = hit_tp and ((not hit_sl) or cfg.both == "Win")
                    gain = t.tp_pts if win else -cfg.sl
                    done = True
                    s.wins += win
                    s.losses += not win
                    s.lRun = 0 if win else s.lRun + 1
                    if not win:
                        s.sesSlId = ses_id
                    if cfg.sk_on and s.lRun >= cfg.sk_n:
                        s.skLeft, s.lRun = cfg.sk_m, 0
                    s.winB += win and t.d == 1
                    s.lossB += (not win) and t.d == 1
                    s.winS += win and t.d == -1
                    s.lossS += (not win) and t.d == -1
                    s.net += gain
                    s.dayPts += gain
                    s.dayW += win
                    s.dayL += not win
                    s.nOpen -= 1
                    if main:
                        nth_rec(t, 1 if win else -1, gain)
                        mo_rec(t, 1 if win else -1, gain)
                        M.sesW[t.ses] += win
                        M.sesL[t.ses] += not win
                        M.sesWB[t.ses] += win and t.d == 1
                        M.sesLB[t.ses] += (not win) and t.d == 1
                        M.sesPts[t.ses] += gain
                        if t.wd >= 0:
                            M.wdW[t.wd] += win
                            M.wdL[t.wd] += not win
                            M.wdWB[t.wd] += win and t.d == 1
                            M.wdLB[t.wd] += (not win) and t.d == 1
                            M.wdPts[t.wd] += gain
                        else:
                            M.wdOut += 1
                        M.nwW[t.nws] += win
                        M.nwL[t.nws] += not win
                        M.nwWB[t.nws] += win and t.d == 1
                        M.nwLB[t.nws] += (not win) and t.d == 1
                        M.nwPts[t.nws] += gain
                        M.mwW[t.mw] += win
                        M.mwL[t.mw] += not win
                        M.mwPts[t.mw] += gain
                        log_row(t, "WIN" if win else "LOSS", gain, t.tp if win else t.sl)
                    day_check(s, main)
                    del opn[k]
                if cfg.be_on and not done and not t.be:
                    fav = a_hi - t.en if t.d == 1 else t.en - a_lo
                    if fav >= cfg.be_pts * cfg.pt:
                        t.be = True
                        t.sl = t.en + t.d * cfg.be_lock * cfg.pt

        # daily limit reached -> cancel pending orders · 'after an SL wait' -> cancel this session's pending orders
        for k in range(len(opn) - 1, -1, -1):
            t = opn[k]
            s = st[t.sc]
            if cfg.day_on and s.dayStop and not t.filled:
                s.skipDay += 1
                s.nOpen -= 1
                cancel(t)
                del opn[k]
        if ses_slw:
            for k in range(len(opn) - 1, -1, -1):
                t = opn[k]
                s = st[t.sc]
                if s.sesSlId == ses_id and t.ses_id == ses_id and not t.filled:
                    s.sesLimSk += 1
                    s.nOpen -= 1
                    if t.sc == sel:
                        M.sesLimSk[ses_now[i]] += 1
                    cancel(t)
                    del opn[k]

        # ── 2) a confirmed ❖ opens a trade / places the pending order, once per spread ──
        k_dir = 1 if ent_b and not ent_s else -1 if ent_s and not ent_b else 0
        if k_dir:
            nw_place_blk = cfg.news_on and nw_place_l[i] == 2
            we_place_blk = we_place[i]
            name = ("BUY" if k_dir == 1 else "SELL") + ((" LIMIT" if lim else " STOP") if pend else "")
            for sc in scen:
                s = st[sc]
                ses_lim_blk = (ses1 and s.sesTrId == ses_id) or (ses_slw and s.sesSlId == ses_id)
                free = (not cfg.one) or s.nOpen == 0
                if cfg.day_on and s.dayStop:
                    s.skipDay += 1
                elif cfg.max_day > 0 and s.day_n >= cfg.max_day:
                    s.skipDay += 1
                    s.maxSkip += 1
                elif not ses_ok_now:
                    s.sesSkip += 1
                    if sc == sel:
                        M.sesSkip[ses_now[i]] += 1
                elif ses_lim_blk:
                    s.sesLimSk += 1
                    if sc == sel:
                        M.sesLimSk[ses_now[i]] += 1
                elif nw_place_blk:
                    s.nwSkip += 1
                elif we_place_blk:
                    s.weSkip += 1
                elif free and cfg.sk_on and s.skLeft > 0:
                    s.skLeft -= 1
                    s.skN += 1
                    if sc == sel:
                        M.tr.append(brk(k_dir, 0, prev_day, 3, ci, op, stp, buy_type, sell_type, ses_now[i], hd, ofd[i],
                                        adx[i], dip[i], dim[i], cfg, day_id[i]))
                elif free:
                    if first_tm is None:
                        first_tm = i
                        days_all = 1
                        mo_slot()[5] += 1
                        if wd_now[i] >= 0:
                            M.wdCnt[wd_now[i]] += 1
                        M.mwCnt[mw_now[i]] += 1
                    en = ci + (-k_dir if lim else k_dir) * off_d if pend else (ci + s.spr if k_dir == 1 else ci)
                    tpp = cfg.tp_lon if cfg.tp_lon > 0 and ses_now[i] == 1 else cfg.tp
                    t = Tr(d=k_dir, en=en, tp=en + k_dir * tpp * cfg.pt, sl=en - k_dir * sl_d, bar=i, filled=not pend,
                           lim=lim, sig=i, sc=sc, ses=ses_now[i], wd=wd_now[i], nws=nw_place_l[i], mw=mw_now[i],
                           ses_id=ses_id, tp_pts=tpp, name=name)
                    s.sesTrId = ses_id
                    s.day_n += 1
                    if sc == sel:
                        nth_day += 1
                        t.nth, t.lot, t.tid = nth_day, lot, len(M.tr)
                        M.lot[3] = max(M.lot[3], lot)
                        M.tr.append(brk(k_dir, nth_day, prev_day, 9, ci, op, stp, buy_type, sell_type, ses_now[i], hd,
                                        ofd[i], adx[i], dip[i], dim[i], cfg, day_id[i]))
                    opn.append(t)
                    s.nOpen += 1

        pk = max(pk, st[sel].net)
        dd = max(dd, pk - st[sel].net)

    rep = dict(w=rep_w, l=rep_l, p=rep_p, fw=rep_fw, fl=rep_fl, fn=rep_fn)
    return dict(st=st, M=M, sel=sel, open=[t for t in opn if t.sc == sel], dd=dd, days=max(days_all, 1),
                first=first_tm, rep=rep, lot_now=lot, events=events)


def brk(d, nth, prev, code, sig_px, op, stp, btype, stype, ses, hd, ofd, adx, dip, dim, cfg, day):
    """🧪 breakdown groups of one ❖ (values when it printed)."""
    x = NAN if (op != op or stp != stp or stp == 0) else (sig_px - op) / stp * d
    return dict(day=day, nth=nth, prev=prev, code=code, pts=0.0, typ=btype if d == 1 else stype, dir=d, ses=ses,
                htf=0 if hd != hd else (1 if (hd < 0) == (d == 1) else -1),
                of=1 if (ofd == ofd and ofd * d >= 0) else -1,
                adx=0 if adx < cfg.adx_min else (1 if (dip >= dim) == (d == 1) else 2),
                loc=-1 if x != x else 0 if x < -1 else 1 if x < 0 else 2 if x < 1 else 3)


# ═════════════════════════════════════════════════════════════════════════════
#  REPORT  (same lines as the Pine Logs "KTR v4 SUMMARY" + the dashboard rows)
# ═════════════════════════════════════════════════════════════════════════════
def rnd(x):
    return int(math.floor(x + 0.5))


def wr(w, l):
    return f" ({rnd(w * 100.0 / (w + l))}%)" if w + l > 0 else ""


def sg(x, dec=0):
    return f"{x:+.{dec}f}".replace("+-", "-") if dec else f"{rnd(x):+d}"


TLOG_RE = None


def tlog_lines(M, df, tz):
    idx = df.index.tz_convert(tz)
    rows = sorted(M.tlog, key=lambda r: (r[0], r[4]))
    return [(f"{idx[a]:%Y-%m-%d %H:%M}", nm, en, res, f"{idx[x]:%Y-%m-%d %H:%M}") for a, nm, en, res, x in rows]


def read_tv_v4(path):
    import re
    if not os.path.isfile(path):
        sys.exit(f"\nCompare file not found: {path}. Copy the 'V4T | …' lines from the TradingView Pine Logs into it\n"
                 f"(Get-Clipboard | Add-Content {path} -Encoding utf8, chunk by chunk).")
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(enc)
            if "\x00" not in text:
                break
        except UnicodeDecodeError:
            continue
    rx = re.compile(r"V4T \| (\d{4}-\d\d-\d\d \d\d:\d\d) \| ((?:BUY|SELL)(?: LIMIT| STOP)?) \| ([\d.]+) \| "
                    r"(WIN|LOSS|CLOSED [+-]?\d+|CANCEL) \| (\d{4}-\d\d-\d\d \d\d:\d\d)")
    out, seen = [], set()
    for ln in text.splitlines():
        m = rx.search(ln)
        if m and ln.strip() not in seen:
            seen.add(ln.strip())
            out.append((m.group(1), m.group(2), float(m.group(3)), m.group(4), m.group(5)))
    return out


def compare_v4(py, tv_path, df, tz):
    from collections import Counter
    tv = read_tv_v4(tv_path)
    if not tv:
        sys.exit(f"No 'V4T | …' lines found in {tv_path}. Did you add the 3 log.info lines to the Pine script?")
    lo, hi = min(r[0] for r in tv), max(r[0] for r in tv)
    py = [r for r in py if lo <= r[0] <= hi]
    kind = lambda r: r[3].split()[0]                          # WIN / LOSS / CLOSED / CANCEL
    key = lambda r: (r[0], r[1], kind(r))
    cp, ct = Counter(map(key, py)), Counter(map(key, tv))
    print(f"\n=== Compare with TradingView V4T log: {lo} -> {hi} (UTC+7 / --tz) ===")
    print(f"TradingView {len(tv)} lines · Python {len(py)} lines · same trade + same result: {sum((cp & ct).values())}")
    # same trade (live time + order) on both sides: how far apart are the entry prices?  (= price feed difference)
    tvd = {}
    for r in tv:
        tvd.setdefault((r[0], r[1]), []).append(r)
    diffs = [abs(r[2] - tvd[(r[0], r[1])][0][2]) for r in py if (r[0], r[1]) in tvd]
    if diffs:
        d = sorted(diffs)
        print(f"Entry price on the same trades ({len(d)}): median difference {d[len(d) // 2]:.3f}, largest {d[-1]:.3f} "
              f"(only the price feed - the rules put the order at the same place)")
    only_tv = sorted((ct - cp).elements())
    only_py = sorted((cp - ct).elements())
    if not only_tv and not only_py:
        print("Every trade and every result matches TradingView.")
        return
    print(f"Different: {len(only_tv)} only/different on TradingView · {len(only_py)} only/different in Python\n")
    pyd = {}
    for r in py:
        pyd.setdefault((r[0], r[1]), []).append(r)
    idx = df.index.tz_convert(tz)
    pos = pd.Series(range(len(idx)), index=idx.strftime("%Y-%m-%d %H:%M"))
    pos = pos[~pos.index.duplicated()]
    done = set()
    for k in sorted(set(only_tv) | set(only_py)):
        t_, nm, _ = k
        if (t_, nm) in done:
            continue
        done.add((t_, nm))
        a = [r for r in tvd.get((t_, nm), [])]
        b = [r for r in pyd.get((t_, nm), [])]
        tvs = "; ".join(f"{r[3]} entry {r[2]:.3f} exit {r[4]}" for r in a) or "— (no such trade)"
        pys = "; ".join(f"{r[3]} entry {r[2]:.3f} exit {r[4]}" for r in b) or "— (no such trade)"
        print(f"  {t_}  {nm}\n     TradingView: {tvs}\n     Python     : {pys}")
        if t_ in pos.index:
            j = int(pos[t_])
            r = df.iloc[j]
            print(f"     CSV candle {t_}: O {r.open:.3f} H {r.high:.3f} L {r.low:.3f} C {r.close:.3f}  -> hover the same candle on TradingView")


def report(res, df, cfg, tz, out):
    st, M, sel = res["st"], res["M"], res["sel"]
    k = st[sel]
    days, dd = res["days"], res["dd"]
    idx = df.index.tz_convert(tz)
    pend_n = sum(1 for t in res["open"] if not t.filled)
    live_n = sum(1 for t in res["open"] if t.filled)
    first = res["first"]
    per = "—" if first is None else f"{idx[first]:%d %b %y} → {idx[-1]:%d %b %y} · {days} days"
    entry = ("At ❖ close" if cfg.entry == "close" else f"{'LIMIT' if cfg.entry == 'limit' else 'STOP'} ±{cfg.off:g} pts · "
             f"{cfg.exp} candles" + (f" / {cfg.run} pts" if cfg.run else ""))
    entry += (f" · skip {cfg.sk_m} after {cfg.sk_n} SL" if cfg.sk_on else "") + \
        (" · 1 per session" if cfg.ses_lim == "one" else " · SL → next session" if cfg.ses_lim == "slwait" else "") + \
        (f" · max {cfg.max_day} ❖/day" if cfg.max_day > 0 else "")
    tpsl = f"+{cfg.tp:g} / −{cfg.sl:g} pts · spread {k.spr:.2f}" + (f" · London TP +{cfg.tp_lon:g}" if cfg.tp_lon > 0 else "")
    flt = (f"HTF {cfg.htf}" + (f" · wick {cfg.wick_pct:g}%" if cfg.wick else "") + (" · wait 1 candle" if cfg.hold else "") +
           (f" · order flow {cfg.of_min:g}%" if cfg.of_on else "") + (f" · ADX {cfg.adx_min:g}" if cfg.adx_on else "") +
           (f" · cheap side max {cfg.cheap_max:g}" if cfg.cheap_max > 0 else "") +
           f" · types {'R' if cfg.t_rev else '-'}{'C' if cfg.t_con else '-'}{'M' if cfg.t_mic else '-'}" +
           f" · BE {f'{cfg.be_pts:g}+{cfg.be_lock:g}' if cfg.be_on else 'off'}" +
           f" · skip after SL {f'{cfg.sk_n}/{cfg.sk_m}' if cfg.sk_on else 'off'} · per session {cfg.ses_lim}" +
           f" · weekend {f'{cfg.we_min} min before Fri close' if cfg.we_on else 'off'}" +
           f" · OP side {cfg.op_filter} · news {'ON' if cfg.news_on else 'off'}" +
           f" · London {'ON' if cfg.ses_lon_on else 'off'}")
    wl = (f"{k.wins}W {k.losses}L{wr(k.wins, k.losses)}" + (f" · {live_n} open" if live_n else "") +
          (f" · {pend_n} pending" if pend_n else "") + (f" · {k.missed} missed" if k.missed else "") +
          (f" · {k.early} closed early" if k.early else "") + (f" · {k.skN} skipped" if cfg.sk_on and k.skN else "") +
          (f" · {k.sesLimSk} session-skipped" if cfg.ses_lim != "off" and k.sesLimSk else ""))
    net = f"{sg(k.net, 2)} pts  ({sg(k.net / cfg.sl, 1)}R) · DD {dd / cfg.sl:.1f}R"
    ddtx = (f"max drawdown {dd / cfg.sl:.1f}R = ${dd * cfg.pt * 100 * 0.01:,.0f} at 0.01 lot · ${dd * cfg.pt * 100 * 0.10:,.0f} at 0.10"
            f" · biggest safe lot for 12% of 10K ≈ {(math.floor(1200 / (dd * cfg.pt * 100) * 100) / 100) if dd > 0 else 0:.2f}")
    lottx = ("off" if not cfg.lot_on else f"${M.lot[0]:+,.2f} · DD ${M.lot[2]:,.2f}  vs fixed {cfg.lot_base:.2f}: "
             f"${k.net * cfg.pt * 100 * cfg.lot_base:+,.2f} · DD ${dd * cfg.pt * 100 * cfg.lot_base:,.2f} · biggest lot {M.lot[3]:.2f}"
             f" · lot now {res['lot_now']:.2f}")
    avg = k.net / days
    avgtx = f"{sg(avg)} pts · {k.wins / days:.1f}W {k.losses / days:.1f}L · ${avg * cfg.pt * 100 * 0.01:+.1f} /0.01 lot"

    print(f"\nData : {len(df):,} bars  {idx[0]:%Y-%m-%d %H:%M} -> {idx[-1]:%Y-%m-%d %H:%M}  (times in {tz})")
    print(f"=== KTR v4 SUMMARY (Python) · {per} ===")
    print(f"Entry: {entry} · {tpsl} · daily limit {f'+{cfg.day_tp:g}/-{cfg.day_sl:g}' if cfg.day_on else 'off'}")
    print(f"Filters: {flt}")
    print(f"Win/Loss: {wl}")
    print(f"Net: {net}")
    print(f"Drawdown: {ddtx}")
    print(f"Lot test: {lottx}")
    print(f"Avg/day: {avgtx}")
    be = cfg.sl * 100.0 / (cfg.tp + cfg.sl)
    print(f"BUY ❖: {k.winB}W {k.lossB}L{wr(k.winB, k.lossB)} · SELL ❖: {k.winS}W {k.lossS}L{wr(k.winS, k.lossS)} · "
          f"break-even win rate {rnd(be)}%")
    print(f"Skipped / cancelled: daily limit {k.skipDay - k.maxSkip} · session OFF {k.sesSkip} · news {k.nwSkip} · weekend {k.weSkip}"
          + (f" · max ❖/day {k.maxSkip}" if cfg.max_day > 0 else "")
          + (f" · per-session rule {k.sesLimSk}" if cfg.ses_lim != "off" else "")
          + (f" · break-even exits {k.beN} ({sg(k.bePts)} pts)" if cfg.be_on else ""))
    print(f"Daily limit days: 🎯 {k.daysTgt} · ⛔ {k.daysLoss} (of {days})")

    # breakdown (same groups as the Pine 🧪 row)
    names = ["Reversal ◇", "Continuation ◇", "Micro-pullback ◇", "BUY", "SELL", "Asia", "London", "New York",
             "Other hours", "1st ❖ of day", "2nd ❖", "3rd ❖", "4th+ ❖", "With 1H trend", "Against 1H trend",
             "Order flow with ❖", "Order flow against ❖", "ADX weak (ranging)", "ADX strong, ❖ with it",
             "ADX strong, ❖ against it", "Cheap: > 1 step past OP", "Cheap: 0–1 step", "Expensive: 0–1 step",
             "Expensive: > 1 step (chasing)"]
    w, ls, p = [0] * 24, [0] * 24, [0.0] * 24
    for r in M.tr:
        if r["code"] not in (1, -1):
            continue
        g = [r["typ"], 3 if r["dir"] == 1 else 4, 5 + r["ses"], 9 + min(max(r["nth"], 1), 4) - 1,
             13 if r["htf"] == 1 else 14 if r["htf"] == -1 else -1, 15 if r["of"] == 1 else 16, 17 + r["adx"],
             20 + r["loc"] if r["loc"] >= 0 else -1]
        for q in g:
            if q >= 0:
                w[q] += r["code"] == 1
                ls[q] += r["code"] == -1
                p[q] += r["pts"]
    print(f"🧪 Breakdown of closed ❖ trades (WIN / LOSS) · spread {k.spr:.2f} · break-even win rate {rnd(be)}%")
    heads = {0: "◇ DIAMOND TYPE", 3: "SIDE", 5: "SESSION (at the ❖)", 9: "❖ OF THE DAY", 13: "1H TREND" if cfg.htf != "4h" else "4H TREND",
             15: "ORDER FLOW", 17: f"ADX ({cfg.adx_min:g})", 20: "LOCATION vs OP (KTR steps)"}
    for q in range(24):
        if q in heads:
            print(f"\n{heads[q]}")
        if w[q] + ls[q]:
            print(f"  {names[q]}:  {w[q]}W {ls[q]}L{wr(w[q], ls[q])} · {sg(p[q])} pts ({sg(p[q] / cfg.sl, 1)}R)")

    # 🔬 filter report
    rp = res["rep"]
    any_f = cfg.htf != "off" or cfg.wick or cfg.hold or cfg.of_on or cfg.adx_on or cfg.cheap_max > 0
    rtx = lambda s: f"{rp['w'][s]}W {rp['l'][s]}L{wr(rp['w'][s], rp['l'][s])} · {sg(rp['p'][s])} pts"
    if cfg.rep_on:
        print("\n🔬 FILTERS: " + ("no ❖ filter on (⓪)" if not any_f else
              f"removed {rp['w'][2] + rp['l'][2]}: {rp['w'][2]}W {rp['l'][2]}L · net {sg(rp['p'][1] - rp['p'][0])} pts vs v3"))
        print(f"v3 ❖ (no filters):  {rtx(0)}\nv4 ❖ (filters on):  {rtx(1)}\n"
              f"Difference: {sg(rp['p'][1] - rp['p'][0])} pts ({sg((rp['p'][1] - rp['p'][0]) / cfg.sl, 1)}R)\n"
              f"❖ removed by the filters (at the moment they printed): {rtx(2)}")
        for q, nm in enumerate([f"Higher-TF trend ({cfg.htf})", f"Rejection wick ({cfg.wick_pct:g}%)",
                                "Order flow / ADX / cheap side", "Wait 1 candle"]):
            print(f"{nm}: {rp['fn'][q]} removed → {rp['fw'][q]}W {rp['fl'][q]}L{wr(rp['fw'][q], rp['fl'][q])}")

    print("\n📆 MONTHS")
    for mk in sorted(M.mo):
        m = M.mo[mk]
        print(f"{MO_NM[mk % 12]} {(mk // 12) % 100:02d}: {m[0]}W {m[1]}L · {sg(m[3])} pts · 🎯{m[6]} ⛔{m[7]}" +
              (f" · fixed {cfg.lot_base:.2f} ${m[3] * cfg.pt * 100 * cfg.lot_base:+,.0f} · lot test ${m[4]:+,.0f}" if cfg.lot_on else "") +
              f" · {m[5]} days")
    # per year (12 months from the first month) - quick check that every year is positive
    yrs = {}
    for mk, m in M.mo.items():
        yrs.setdefault(mk // 12, 0.0)
        yrs[mk // 12] += m[3]
    print("📅 YEARS: " + " · ".join(f"{y}: {sg(v / cfg.sl, 1)}R" for y, v in sorted(yrs.items())))
    print("=== END ===")

    # dashboard rows
    print("\nSpreads (each runs on its own):")
    for sc, s in enumerate(st):
        if sc == sel or cfg.spread_cmp:
            print(f"  {'● ' if sc == sel else '  '}Spread {s.spr:.2f}: {s.wins}W {s.losses}L{wr(s.wins, s.losses)} · "
                  f"{sg(s.net)} pts ({sg(s.net / cfg.sl, 1)}R) · missed {s.missed} · 🎯{s.daysTgt} ⛔{s.daysLoss}")
    print(f"\nSessions ({cfg.ses_tz}, counted where the trade went live):")
    ses_on = [cfg.ses_asia_on, cfg.ses_lon_on, cfg.ses_ny_on, cfg.ses_other_on]
    hrs = [cfg.ses_asia, cfg.ses_lon, cfg.ses_ny, "outside"]
    for q in range(4):
        tx = (f"{M.sesW[q]}W {M.sesL[q]}L{wr(M.sesW[q], M.sesL[q])} · {sg(M.sesPts[q])} pts" if ses_on[q]
              else f"OFF · {M.sesSkip[q]} ❖ skipped")
        print(f"  {SES_NM[q]:<9}{hrs[q]:<10} {tx}")
    print("\n❖ of the day:")
    for q in range(4):
        nn = M.nthW[q] + M.nthL[q] + M.nthE[q]
        print(f"  {['1st', '2nd', '3rd', '4th+'][q]:<5} {M.nthW[q]}W {M.nthL[q]}L{wr(M.nthW[q], M.nthL[q])} · {sg(M.nthPts[q])} pts · "
              f"avg {sg(M.nthPts[q] / nn) if nn else '—'}" + (f" · {M.nthM[q]} missed" if M.nthM[q] else ""))
    print(f"\nWeekdays ({cfg.ses_tz}):")
    for q in range(5):
        print(f"  {WD_NM[q]}  {M.wdW[q]}W {M.wdL[q]}L{wr(M.wdW[q], M.wdL[q])} · {sg(M.wdPts[q])} pts" +
              (f"  │ 🎯{M.wdTgt[q]} ⛔{M.wdLoss[q]}" if cfg.day_on and M.wdTgt[q] + M.wdLoss[q] else ""))
    print("\nWeeks of the month:")
    for q, rg in enumerate(["1–7", "8–14", "15–21", "22–end"]):
        print(f"  Week {q + 1} ({rg:<6}) {M.mwW[q]}W {M.mwL[q]}L{wr(M.mwW[q], M.mwL[q])} · {sg(M.mwPts[q])} pts" +
              (f"  │ 🎯{M.mwTgt[q]} ⛔{M.mwLoss[q]}" if cfg.day_on and M.mwTgt[q] + M.mwLoss[q] else ""))
    print("\nNews zones (where the trade went live):")
    for q, nm in enumerate(["No news near", "Before news", "News window", "After news"]):
        print(f"  {nm:<13} {M.nwW[q]}W {M.nwL[q]}L{wr(M.nwW[q], M.nwL[q])} · {sg(M.nwPts[q])} pts" +
              (f" · {k.nwSkip} ❖ skipped" if q == 2 and cfg.news_on else ""))
    for typ, nm in ((1, "⛔ → next day"), (2, "🎯 → next day")):
        ww, ll = [0, 0, 0], [0, 0, 0]
        for r in M.tr:
            if r["prev"] == typ and 1 <= r["nth"] <= 3:
                ww[r["nth"] - 1] += r["code"] == 1
                ll[r["nth"] - 1] += r["code"] == -1
        print(f"{nm}: " + " · ".join(f"{['1st', '2nd', '3rd'][q]} {ww[q]}W {ll[q]}L{wr(ww[q], ll[q])}" for q in range(3)))
    nf = sum(1 for e in res["events"] if e[2] == "NFP (auto)")
    print(f"\nNews times used: {len(res['events']) - nf} from the list (covers {NEWS_SPAN}) + {nf} auto NFP (first Fridays)"
          + ("" if cfg.nfp else " - auto NFP is OFF"))

    if out and M.rows:
        rows = [(idx[a], idx[b], idx[x], nm, round(en, 3), round(tp, 3), round(sl, 3), r, round(pt, 1), ses, nth, lot, round(px, 3))
                for a, b, x, nm, en, tp, sl, r, pt, ses, nth, lot, px in M.rows]
        pd.DataFrame(rows, columns=["signal_candle", "live_candle", "exit_candle", "order", "entry", "tp", "sl", "result",
                                    "pts", "session", "nth_of_day", "lot", "exit_price"]).to_csv(out, index=False)
        print(f"Every closed ❖ trade (spread {k.spr:.2f}) saved to {out}")


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════════════
NEWS_TEXT = NEWS_DEFAULT
SPEECH_TEXT = ""
NEWS_SPAN = "Jul–Dec 2026"


def main():
    global NEWS_TEXT, SPEECH_TEXT, NEWS_SPAN
    ap = argparse.ArgumentParser(description="KTR v4 - Python backtest of the Pine v6 indicator (❖ trades)",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("csv", nargs="?", help="15-minute OHLC(V) CSV (1m / 5m files are converted to 15m; bigger candles are refused)")
    ap.add_argument("--demo", action="store_true", help="synthetic random data (just to test the script)")
    ap.add_argument("--data-tz", default="UTC", help="timezone of timestamps that carry none (default UTC)")
    ap.add_argument("--tz", default="Asia/Bangkok", help="timezone for printed times / --start / --end (default UTC+7)")
    ap.add_argument("--session-tz", default="America/New_York", help="where the trading day (OP) rolls (default New York)")
    ap.add_argument("--session-hour", type=float, default=17.0, help="hour the new daily open starts (default 17)")
    ap.add_argument("--start", help="only bars from this date/time (in --tz)")
    ap.add_argument("--end", help="only bars up to this date/time (in --tz)")
    ap.add_argument("--last", type=int, help="only the last N bars (5000 = TradingView free plan)")
    ap.add_argument("--news-file", help="text file with news times, one per line 'YYYY-MM-DD HH:MM | name' (replaces the Pine default list)")
    ap.add_argument("--speech-file", help="text file with speeches, same format")
    ap.add_argument("--set", action="append", metavar="KEY=VALUE", help="override a setting, repeatable")
    ap.add_argument("--show-settings", action="store_true", help="print all settings and exit")
    ap.add_argument("--out", default="trades_v4.csv", help="where to save every closed trade (default trades_v4.csv)")
    ap.add_argument("--log", default="trades_v4_log.txt", help="every ❖ trade in the same 'V4T | …' format as the Pine log (default trades_v4_log.txt)")
    ap.add_argument("--compare", metavar="TV_LOG", help="text file with the 'V4T | …' lines copied from TradingView Pine Logs")
    args = ap.parse_args()

    cfg = Config()
    apply_overrides(cfg, args.set)
    if args.show_settings:
        for f in fields(cfg):
            print(f"{f.name:<14} = {getattr(cfg, f.name)}")
        return
    if args.news_file:
        NEWS_TEXT = open(args.news_file, encoding="utf-8").read()
        dts = [e[0] for e in parse_events(NEWS_TEXT, cfg.news_tz, 0)]
        NEWS_SPAN = (f"{pd.Timestamp(min(dts), unit='ms'):%b %Y}–{pd.Timestamp(max(dts), unit='ms'):%b %Y}" if dts else "nothing")
    if args.speech_file:
        SPEECH_TEXT = open(args.speech_file, encoding="utf-8").read()

    if args.demo:
        df = kb.demo_data()
        df = kb.resample(df, "15min")
        print("DEMO MODE: synthetic random data. Numbers below mean nothing - this only checks the script runs.")
    elif args.csv:
        if not os.path.isfile(args.csv):
            sys.exit(f"File not found: {args.csv}  (looking in {os.getcwd()})\n"
                     f"Export 15-minute candles first:  python export_mt5_5m.py --tf M15")
        df = kb.load_csv(args.csv, args.data_tz)
    else:
        ap.error("give a CSV file, or use --demo")
    if args.start:
        df = df[df.index >= pd.Timestamp(args.start, tz=args.tz)]
    if args.end:
        df = df[df.index <= pd.Timestamp(args.end, tz=args.tz)]
    if args.last:
        df = df.tail(args.last)
    if len(df) < 300:
        sys.exit(f"Only {len(df)} bars after filtering - need at least a few hundred.")
    # KTR v4 runs on 15-minute candles only: smaller candles are built into 15m automatically, bigger ones are refused
    step = df.index.to_series().diff().median()
    m15 = pd.Timedelta(minutes=15)
    if step < m15 and m15 % step == pd.Timedelta(0):
        print(f"Data has {int(step.total_seconds() // 60)}-minute candles -> building 15-minute candles from them "
              f"(KTR v4 runs on 15m only).")
        df = kb.resample(df, "15min")
        step = m15
    elif step != m15:
        sys.exit(f"KTR v4 runs on 15-minute candles only, but this file has {int(step.total_seconds() // 60)}-minute candles.\n"
                 f"Export 15m candles:  python export_mt5_5m.py --tf M15   (or use a 1m / 5m file - it is converted to 15m)")
    if cfg.vol_on and not (df["volume"] > 0).any():
        print("WARNING: no volume in the data -> the ❖ volume filter is switched OFF.")
        cfg.vol_on = False

    day_id = kb.make_day_ids(df.index, args.session_tz, args.session_hour)
    res = simulate(df, cfg, day_id, int(step.total_seconds() * 1000), args.session_tz, args.session_hour)
    report(res, df, cfg, args.tz, args.out)
    lines = tlog_lines(res["M"], df, args.tz)
    if args.log:
        with open(args.log, "w", encoding="utf-8") as f:
            for a, nm, en, r, x in lines:
                f.write(f"V4T | {a} | {nm} | {en:.3f} | {r} | {x}\n")
        print(f"Trade log ({len(lines)} lines, same format as the Pine 'V4T' log) saved to {args.log}")
    if args.compare:
        compare_v4(lines, args.compare, df, args.tz)


if __name__ == "__main__":
    main()
