"""
Parte B — Backtest de setups clásicos EMA + RSI con parámetros estándar (sin optimizar).

Cada setup se prueba en largo y en corto, en 6 mercados y 4 timeframes, con dos
paquetes de salida para separar la calidad de la ENTRADA de la de la salida:
  - "nativa":  la salida propia del setup + stop de protección de 2 ATR.
  - "bracket": stop 1,5 ATR, objetivo 3 ATR (2R), salida por tiempo a las 20 barras.

Intradía (5m/15m): entradas 09:30-15:00 ET, todo se cierra a las 16:00 ET.
Swing (1h/1d): se mantiene overnight.

Resultados en R (múltiplos del riesgo inicial) NETOS de costos (lib.COST_PTS).
Salida: results/setups.csv
"""
import os

import numpy as np
import pandas as pd

from lib import COST_PTS, IS_END, NAMES, add_indicators, load, metrics, session_masks, simulate, years_span

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
TFS = ["5m", "15m", "1h", "1d"]


def _prev(x):
    return x.shift() if isinstance(x, pd.Series) else x


def cross_up(a, b):
    return (a > b) & (a.shift() <= _prev(b))


def cross_dn(a, b):
    return (a < b) & (a.shift() >= _prev(b))


def in_sample(times):
    t = times.dt.tz_localize(None) if times.dt.tz is not None else times
    return (t < pd.Timestamp(IS_END) + pd.Timedelta(days=1)).values


def setups(df):
    """Devuelve {nombre: (entrada_largo, salida_largo, entrada_corto, salida_corto)}."""
    c, e5, e9, e21, e50, e200 = (df[k] for k in ("close", "ema5", "ema9", "ema21", "ema50", "ema200"))
    r14, r2 = df["rsi14"], df["rsi2"]
    bull, bear = df["regime"] == "Alcista", df["regime"] == "Bajista"
    s = {}
    s["S1 Cruce EMA 9/21"] = (
        cross_up(e9, e21), e9 < e21,
        cross_dn(e9, e21), e9 > e21)
    s["S2 Cruce 9/21 + RSI>50 + EMA200"] = (
        cross_up(e9, e21) & (r14 > 50) & (c > e200), e9 < e21,
        cross_dn(e9, e21) & (r14 < 50) & (c < e200), e9 > e21)
    s["S3 RSI 30/70 contra-tendencia"] = (
        cross_up(r14, 30), r14 > 50,
        cross_dn(r14, 70), r14 < 50)
    s["S4 RSI 30/70 a favor de tendencia"] = (
        cross_up(r14, 30) & bull, r14 > 50,
        cross_dn(r14, 70) & bear, r14 < 50)
    s["S5 RSI(2) extremo + EMA200"] = (
        (r2 < 10) & (c > e200), c > e5,
        (r2 > 90) & (c < e200), c < e5)
    s["S6 Retroceso a EMA21 en tendencia"] = (
        (e21 > e50) & (e50 > e200) & (df["low"] <= e21) & (c > e21) & r14.between(40, 60), c < e50,
        (e21 < e50) & (e50 < e200) & (df["high"] >= e21) & (c < e21) & r14.between(40, 60), c > e50)
    s["S7 Impulso RSI 70/30 en tendencia"] = (
        cross_up(r14, 70) & bull, r14 < 50,
        cross_dn(r14, 30) & bear, r14 > 50)
    return s


def run_one(inst, tf):
    df = add_indicators(load(inst, tf))
    allow, force = session_masks(df, tf)
    cost = COST_PTS[inst]
    native_max = {"5m": 1000, "15m": 1000, "1h": 100, "1d": 100}[tf]
    rows, trades_out = [], {}
    for name, (el, xl, es, xs) in setups(df).items():
        for side, ent, ex, d in (("Largo", el, xl, 1), ("Corto", es, xs, -1)):
            ent = ent.fillna(False).values & allow
            ex = ex.fillna(False).values
            for exit_mode in ("nativa", "bracket"):
                if exit_mode == "nativa":
                    mx = 20 if name.startswith("S5") else native_max
                    tr = simulate(df, ent, ex, force, d, stop_mult=2.0, target_mult=0.0, max_bars=mx, cost=cost)
                else:
                    tr = simulate(df, ent, np.zeros(len(df), bool), force, d,
                                  stop_mult=1.5, target_mult=3.0, max_bars=20, cost=cost)
                is_mask = in_sample(tr["entry_time"])
                yrs = years_span(df.index)
                yrs_is = years_span(df.loc[:IS_END].index)
                yrs_oos = years_span(df.loc[IS_END:].index)
                row = dict(inst=inst, tf=tf, setup=name, side=side, exit=exit_mode)
                row.update(metrics(tr, yrs))
                for tag, m, y in (("IS", is_mask, yrs_is), ("OOS", ~is_mask, yrs_oos)):
                    mm = metrics(tr[m], y)
                    row[f"{tag}_trades"], row[f"{tag}_avgR"], row[f"{tag}_PF"], row[f"{tag}_t"] = \
                        mm["trades"], mm["avgR"], mm["PF"], mm["t"]
                rows.append(row)
                trades_out[(name, side, exit_mode)] = tr
    return rows, trades_out


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for inst in NAMES:
        for tf in TFS:
            r, _ = run_one(inst, tf)
            rows += r
            print(f"{inst:11s} {tf:>3s} ok")
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(OUT, "setups.csv"), index=False)


if __name__ == "__main__":
    main()
