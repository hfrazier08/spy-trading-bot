#!/usr/bin/env python3
"""
Profit-taking test for the trend-gated 60-day bull call spread (SPY).

The old +100% target is unreachable (needs ~81-97% of the spread's max value). Here the target is
expressed the way a person can actually act on it: a fraction of the spread's MAX PROFIT.
  value >= debit + f * (width - debit)      e.g. f=0.5 -> "close once half the possible profit is banked"
Stop stays at -50% of the debit and the position is always closed 3 days before expiry.
Entry rule is unchanged (flat and close > 200d SMA, one position at a time).

Rules were fixed before looking: f in {none, .25, .40, .50, .60, .75}. Periods are judged separately:
  1996-2007 (dot-com crash, true hold-out), 2008-2016, 2017-2026.

Usage: python backtest/tp_lab.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import strategy_lab as sl  # noqa: E402


def spread_tp(m: sl.Market, i: int, f, dte=60, sl_pct=-0.5, buf=3):
    d0 = m.dates[i]
    expiry = d0 + np.timedelta64(dte, "D")
    if m.dates[-1] < expiry:
        return None
    S0, T0 = m.close[i], dte / 365
    s0 = m.vix[i] / 100 * m.mult
    Kl, Ks = np.ceil(S0), np.ceil(S0 * 1.04)
    c = sl.COST * S0
    debit = (float(sl.call(S0, Kl, T0, s0)) + c) - (float(sl.call(S0, Ks, T0, s0)) - c)
    width = Ks - Kl
    if debit < 0.05 or debit >= width:
        return None
    js = np.arange(i + 1, int(np.searchsorted(m.dates, expiry, side="right")))
    if len(js) < 2:
        return None
    T = (expiry - m.dates[js]).astype(int) / 365
    S, sg = m.close[js], m.vix[js] / 100 * m.mult
    val = (sl.call(S, Kl, T, sg) - c) - (sl.call(S, Ks, T, sg) + c)
    pct = val / debit - 1
    left = (expiry - m.dates[js]).astype(int)
    stop = (pct <= sl_pct) | (left <= buf)
    if f is not None:
        stop |= val >= debit + f * (width - debit)
    k = int(np.argmax(stop)) if stop.any() else len(js) - 1
    return float(pct[k]), js[k]


def stats(t: pd.DataFrame, years: float) -> dict:
    if len(t) < 8:
        return {"n": len(t)}
    x = t["ret"].values
    eq = np.cumsum(x)
    return {"trades/yr": round(len(t) / years, 1), "win%": round((x > 0).mean() * 100, 1),
            "avg%": round(x.mean() * 100, 1), "worst%": round(x.min() * 100),
            "units/yr": round(eq[-1] / years, 2), "maxDD": round(float((eq - np.maximum.accumulate(eq)).min()), 1)}


def main():
    m_early = sl.Market("SPY", start="1996-01-01", end="2008-06-30")
    m_main = sl.Market("SPY")
    periods = [("1996-2007 (hold-out)", m_early, pd.Timestamp("2008-01-01"), None, pd.Timestamp("2008-01-01")),
               ("2008-2016", m_main, None, None, pd.Timestamp("2017-01-01")),
               ("2017-2026", m_main, None, pd.Timestamp("2017-01-01"), None)]
    fs = [None, 0.25, 0.40, 0.50, 0.60, 0.75]
    gate = sl.GATES[">200d"]
    out = {}
    for f in fs:
        fn = lambda mm, ii, f=f: spread_tp(mm, ii, f)
        for name, m, entry_end, lo, hi in periods:
            t = sl.run(m, fn, gate, entry_end=entry_end)
            if lo is not None:
                t = t[t["date"] >= lo]
            if hi is not None:
                t = t[t["date"] < hi]
            yrs = (t["date"].max() - t["date"].min()).days / 365.25 if len(t) > 1 else 1
            out[(f, name)] = stats(t, max(yrs, 1))
    names = [p[0] for p in periods]
    for name in names:
        print(f"\n=== SPY {name}   (avg% = average return on the debit paid, per trade) ===")
        print(pd.DataFrame({("no target" if f is None else f"close @ {int(f*100)}% of max profit"): out[(f, name)] for f in fs}).T.to_string())
    print("\n=== SUMMARY: units of profit per year (1 unit = the debit risked per trade), by period ===")
    rows = []
    for f in fs:
        rows.append({"target": "none (hold to stop/expiry)" if f is None else f"{int(f*100)}% of max profit",
                     **{n: out[(f, n)].get("units/yr") for n in names},
                     **{n + " win%": out[(f, n)].get("win%") for n in names}})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
