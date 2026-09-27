"""
Indicadores, máscaras de sesión y simulador de operaciones compartidos por los estudios.

Convenciones (iguales a NinjaTrader 8 para que los resultados sean trasladables):
  - EMA: alpha = 2 / (n + 1)
  - RSI y ATR: suavizado de Wilder (alpha = 1 / n)
  - Las señales se evalúan al CIERRE de la barra i y se ejecutan en la APERTURA de i+1.
"""
import os

import numpy as np
import pandas as pd
from numba import njit

HERE = os.path.dirname(os.path.abspath(__file__))
BARS_DIR = os.path.join(HERE, "data", "bars")

# Costo ida y vuelta (comisión + deslizamiento) en puntos de precio, equivalente al futuro
# de CME más cercano: NQ, ES, RTY, GC, 6E, CL.
COST_PTS = {
    "NAS100_USD": 1.00,   # NQ: 2 ticks de deslizamiento + comisión ≈ 0,75 pt; redondeado arriba
    "SPX500_USD": 0.50,   # ES: 1 tick por lado + comisión
    "US2000_USD": 0.30,   # RTY
    "XAU_USD":    0.30,   # GC
    "EUR_USD":    0.00015,  # 6E: 1,5 pips
    "WTICO_USD":  0.03,   # CL
}
NAMES = {
    "NAS100_USD": "NQ (Nasdaq 100)",
    "SPX500_USD": "ES (S&P 500)",
    "US2000_USD": "RTY (Russell 2000)",
    "XAU_USD": "GC (Oro)",
    "EUR_USD": "6E (EUR/USD)",
    "WTICO_USD": "CL (Petróleo WTI)",
}
IS_END = "2012-12-31"  # 2005-2012 = in-sample, 2013-2020 = out-of-sample


def load(inst, tf):
    return pd.read_pickle(os.path.join(BARS_DIR, f"{inst}_{tf}.pkl"))


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100.0).where(up.notna())


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def add_indicators(df):
    df = df.copy()
    c = df["close"]
    for n in (5, 9, 21, 50, 200):
        df[f"ema{n}"] = ema(c, n)
    df["rsi2"] = rsi(c, 2)
    df["rsi14"] = rsi(c, 14)
    df["atr"] = atr(df, 14)
    a = df["atr"]
    df["d21"] = (c - df["ema21"]) / a
    df["d50"] = (c - df["ema50"]) / a
    df["d200"] = (c - df["ema200"]) / a
    df["slope21"] = (df["ema21"] - df["ema21"].shift(5)) / a
    df["gap_9_21"] = (df["ema9"] - df["ema21"]) / a
    bull = (c > df["ema200"]) & (df["ema50"] > df["ema200"])
    bear = (c < df["ema200"]) & (df["ema50"] < df["ema200"])
    df["regime"] = np.select([bull, bear], ["Alcista", "Bajista"], "Neutral")
    df["stack"] = np.select(
        [(df["ema9"] > df["ema21"]) & (df["ema21"] > df["ema50"]),
         (df["ema9"] < df["ema21"]) & (df["ema21"] < df["ema50"])],
        ["Alineadas al alza", "Alineadas a la baja"], "Mezcladas")
    # Descarta el calentamiento de la EMA 200
    return df.iloc[250:]


def session_masks(df, tf):
    """Devuelve (entrada_permitida, cierre_forzado) para el modo del timeframe.

    5m / 15m -> modo intradía: solo se abren operaciones en RTH (09:30-15:00 ET) y todo
                se cierra al final de la sesión regular (16:00 ET). Sin posiciones overnight.
    1h / 1d  -> modo swing: se puede entrar en cualquier barra y mantener overnight.
    """
    n = len(df)
    if tf not in ("5m", "15m"):
        return np.ones(n, bool), np.zeros(n, bool)
    t = df.index
    minutes = t.hour * 60 + t.minute
    step = 5 if tf == "5m" else 15
    rth = (minutes >= 9 * 60 + 30) & (minutes < 16 * 60)
    allow = (minutes >= 9 * 60 + 30) & (minutes <= 15 * 60)
    date = t.normalize()
    nxt_rth = np.r_[rth[1:], False]
    nxt_same_day = np.r_[date[1:] == date[:-1], False]
    last_rth = rth & ~(nxt_rth & nxt_same_day)
    # También cierra si la barra siguiente cae después de las 16:00 (días de cierre temprano)
    last_rth |= rth & (minutes + step >= 16 * 60)
    return np.asarray(allow & ~last_rth), np.asarray(last_rth)


@njit(cache=True)
def _simulate(o, h, l, c, a, entry, exit_sig, force_exit, direction, stop_mult, target_mult, max_bars, cost):
    n = len(c)
    ei = np.empty(n, np.int64)
    xi = np.empty(n, np.int64)
    rr = np.empty(n)
    pts = np.empty(n)
    rk = np.empty(n)
    k = 0
    next_free = 0
    for i in range(n - 1):
        if not entry[i] or i < next_free or force_exit[i]:
            continue
        risk = stop_mult * a[i]
        if not (risk > 0):
            continue
        e = o[i + 1]
        stop = e - direction * risk
        has_tgt = target_mult > 0
        tgt = e + direction * target_mult * a[i]
        j = i + 1
        x = np.nan
        while True:
            first = j == i + 1
            if direction == 1:
                if l[j] <= stop:  # stop primero si stop y objetivo caen en la misma barra
                    x = stop if first else min(o[j], stop)
                    break
                if has_tgt and h[j] >= tgt:
                    x = tgt if first else max(o[j], tgt)
                    break
            else:
                if h[j] >= stop:
                    x = stop if first else max(o[j], stop)
                    break
                if has_tgt and l[j] <= tgt:
                    x = tgt if first else min(o[j], tgt)
                    break
            if force_exit[j] or j == n - 1 or (j - i) >= max_bars:
                x = c[j]
                break
            if exit_sig[j]:
                if force_exit[j + 1]:
                    x = c[j]
                else:
                    j += 1
                    x = o[j]
                break
            j += 1
        p = direction * (x - e) - cost
        ei[k] = i + 1
        xi[k] = j
        pts[k] = p
        rr[k] = p / risk
        rk[k] = risk
        k += 1
        next_free = j
    return ei[:k], xi[:k], rr[:k], pts[:k], rk[:k]


def simulate(df, entry, exit_sig, force_exit, direction, stop_mult=2.0, target_mult=0.0, max_bars=100, cost=0.0):
    ei, xi, rr, pts, rk = _simulate(
        df["open"].values, df["high"].values, df["low"].values, df["close"].values, df["atr"].values,
        np.asarray(entry, bool), np.asarray(exit_sig, bool), np.asarray(force_exit, bool),
        direction, stop_mult, target_mult, max_bars, cost)
    return pd.DataFrame({"entry_time": df.index[ei], "exit_time": df.index[xi], "bars": xi - ei + 1,
                         "R": rr, "pts": pts, "R_gross": rr + cost / rk})


def metrics(trades, years):
    r = trades["R"].values
    n = len(r)
    if n == 0:
        return dict(trades=0, per_year=0.0, win=np.nan, avgR=np.nan, avgR_gross=np.nan, PF=np.nan, t=np.nan,
                    totR=0.0, maxDD_R=np.nan, bars=np.nan)
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    eq = np.cumsum(r)
    dd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    sd = r.std(ddof=1) if n > 1 else np.nan
    return dict(
        trades=n,
        per_year=n / years,
        win=(r > 0).mean() * 100,
        avgR=r.mean(),
        avgR_gross=trades["R_gross"].mean(),
        PF=wins / losses if losses > 0 else np.inf,
        t=r.mean() / sd * np.sqrt(n) if sd and sd > 0 else np.nan,
        totR=r.sum(),
        maxDD_R=dd,
        bars=trades["bars"].mean(),
    )


def years_span(idx):
    return max((idx[-1] - idx[0]).days / 365.25, 1e-9)
