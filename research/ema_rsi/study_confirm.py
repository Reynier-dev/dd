"""
Parte G — Setups por confluencia: cruce + confirmaciones + retroceso a la EMA.

Secuencia (largo; el corto es el espejo):
  1. CRUCE: la EMA 25 y la EMA 50 quedan ambas por encima de la EMA 200 (la vela en que
     se completa el cruce de la segunda). Desde ahí el setup queda "armado" hasta 100 velas
     o hasta que la EMA 50 vuelva a perder la EMA 200.
  2. CONFIRMACIÓN RSI(14), cuatro variantes:
        ninguna         -> sin condición
        impulso         -> el RSI llegó a sobrecompra (>= 70) después del cruce
        retroceso       -> en el retroceso el RSI bajó a <= 40 (sobreventa dentro de tendencia)
        impulso+retroceso -> ambas
  3. BIAS DIARIO: régimen EMA 50/200 de la sesión diaria ANTERIOR alcista (o sin filtro).
  4. ENTRADA en el apoyo: la vela toca la EMA (25 o 50) con el mínimo y cierra por encima.
     "primer apoyo" = solo el primer toque tras el cruce; "cualquier apoyo" = todos.
  5. SALIDAS: "bracket 2R" (stop 1,5 ATR, objetivo 3 ATR, máx. 50 velas) o
     "trailing EMA 50" (stop 2 ATR, salida al cerrar del otro lado de la EMA 50, máx. 200).

Intradía (5m/15m): entradas 09:30-15:00 ET y cierre obligado 16:00 ET, como en la Parte B.
Salida: results/confirm.csv, results/confirm_effects.csv
"""
import os

import numpy as np
import pandas as pd
from numba import njit

from lib import COST_PTS, NAMES, add_indicators, ema, load, metrics, session_masks, simulate, years_span
from study_mtf import REG
from study_setups import in_sample

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
TFS = ["5m", "15m", "1h", "1d"]
RSI_MODES = {0: "ninguna", 1: "impulso (RSI>=70)", 2: "retroceso (RSI<=40)", 3: "impulso + retroceso"}
WINDOW = 100


@njit(cache=True)
def confirm_signals(c, l, h, e_fast, e_mid, e_slow, e_touch, rsi, bias, allow,
                    direction, rsi_mode, first_only, window, rsi_ob, rsi_os):
    n = len(c)
    out = np.zeros(n, np.bool_)
    armed = False
    cross_bar = 0
    impulse = False
    for i in range(3, n):
        if direction == 1:
            both = e_fast[i] > e_slow[i] and e_mid[i] > e_slow[i]
            both_prev = e_fast[i - 1] > e_slow[i - 1] and e_mid[i - 1] > e_slow[i - 1]
            trend_ok = e_mid[i] > e_slow[i]
        else:
            both = e_fast[i] < e_slow[i] and e_mid[i] < e_slow[i]
            both_prev = e_fast[i - 1] < e_slow[i - 1] and e_mid[i - 1] < e_slow[i - 1]
            trend_ok = e_mid[i] < e_slow[i]
        if both and not both_prev:
            armed = True
            cross_bar = i
            impulse = False
        if not armed:
            continue
        if not trend_ok or i - cross_bar > window:
            armed = False
            continue
        if (direction == 1 and rsi[i] >= rsi_ob) or (direction == -1 and rsi[i] <= 100 - rsi_ob):
            impulse = True
        if i == cross_bar or not allow[i]:
            continue
        if direction == 1:
            touch = l[i] <= e_touch[i] and c[i] > e_touch[i]
        else:
            touch = h[i] >= e_touch[i] and c[i] < e_touch[i]
        if not touch:
            continue
        ok = bias[i] == direction
        if rsi_mode == 1 or rsi_mode == 3:
            ok = ok and impulse
        if rsi_mode == 2 or rsi_mode == 3:
            if direction == 1:
                ok = ok and min(rsi[i], rsi[i - 1], rsi[i - 2]) <= rsi_os
            else:
                ok = ok and max(rsi[i], rsi[i - 1], rsi[i - 2]) >= 100 - rsi_os
        if ok:
            out[i] = True
        if first_only:
            armed = False
    return out


def daily_bias(df, inst):
    """Régimen EMA 50/200 de la sesión diaria anterior (ya cerrada), mapeado a cada vela."""
    d1 = add_indicators(load(inst, "1d"))
    prev = d1["regime"].map(REG).shift(1)
    session = (df.index + pd.Timedelta(hours=6)).normalize()
    if session.tz is not None:
        session = session.tz_localize(None)
    return prev.reindex(session).fillna(0).values


def paired_effects(res):
    """Aporte de cada confirmación: cada variante contra su gemela idéntica sin esa confirmación
    (mismo mercado, TF, lado, EMA de apoyo, primer/cualquier apoyo y salida), en R ANTES de costos."""
    r = res[res.tf != "1d"]
    key = ["inst", "tf", "side", "touch", "first", "exit"]
    base = r[(r.rsi == "ninguna") & (r.bias == "sin bias")].set_index(key)
    variants = [
        ("RSI impulso (>=70)", "impulso (RSI>=70)", "sin bias"),
        ("RSI retroceso (<=40)", "retroceso (RSI<=40)", "sin bias"),
        ("Impulso + retroceso", "impulso + retroceso", "sin bias"),
        ("Bias diario", "ninguna", "bias diario"),
        ("Todo: impulso + bias diario", "impulso (RSI>=70)", "bias diario"),
        ("Todo: impulso + retroceso + bias", "impulso + retroceso", "bias diario"),
    ]
    rows = []
    for label, rsi_mode, bias in variants:
        j = r[(r.rsi == rsi_mode) & (r.bias == bias)].set_index(key).join(base, rsuffix="_b", how="inner")
        j = j[(j.trades >= 20) & (j.trades_b >= 20)]
        d = j.avgR_gross - j.avgR_gross_b
        rows.append(dict(confirm=label, pares=len(j), delta_bruto=d.mean(), se=d.std() / np.sqrt(len(d)),
                         mejora_pct=(d > 0).mean() * 100, trades_ratio=(j.trades / j.trades_b).median(),
                         bruto_con=j.avgR_gross.mean(), bruto_sin=j.avgR_gross_b.mean(), neto_con=j.avgR.mean()))
    return pd.DataFrame(rows)


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for inst in NAMES:
        for tf in TFS:
            df = add_indicators(load(inst, tf))
            df["ema25"] = ema(load(inst, tf)["close"], 25).reindex(df.index)
            allow, force = session_masks(df, tf)
            cost = COST_PTS[inst]
            yrs = years_span(df.index)
            bias_d = daily_bias(df, inst) if tf != "1d" else None
            arr = {k: df[k].values for k in ("close", "low", "high", "ema25", "ema50", "ema200", "rsi14")}
            biases = [("sin bias", None)] + ([("bias diario", bias_d)] if bias_d is not None else [])
            for d, side in ((1, "Largo"), (-1, "Corto")):
                for bias_name, b in biases:
                    barr = np.full(len(df), d, np.float64) if b is None else b.astype(np.float64)
                    for touch_name in ("EMA 25", "EMA 50"):
                        et = arr["ema25"] if touch_name == "EMA 25" else arr["ema50"]
                        for first_name, first in (("primer apoyo", True), ("cualquier apoyo", False)):
                            for mode, mode_name in RSI_MODES.items():
                                ent = confirm_signals(arr["close"], arr["low"], arr["high"], arr["ema25"], arr["ema50"],
                                                      arr["ema200"], et, arr["rsi14"], barr, allow,
                                                      d, mode, first, WINDOW, 70.0, 40.0)
                                for exit_name in ("bracket 2R", "trailing EMA 50"):
                                    if exit_name == "bracket 2R":
                                        tr = simulate(df, ent, np.zeros(len(df), bool), force, d, 1.5, 3.0, 50, cost)
                                    else:
                                        ex = (df["close"] < df["ema50"]).values if d == 1 else (df["close"] > df["ema50"]).values
                                        tr = simulate(df, ent, ex, force, d, 2.0, 0.0, 200, cost)
                                    ism = in_sample(tr["entry_time"])
                                    row = dict(inst=inst, tf=tf, side=side, bias=bias_name, touch=touch_name,
                                               first=first_name, rsi=mode_name, exit=exit_name)
                                    row.update(metrics(tr, yrs))
                                    row["IS_trades"], row["OOS_trades"] = int(ism.sum()), int((~ism).sum())
                                    row["IS_avgR"], row["OOS_avgR"] = tr["R"][ism].mean(), tr["R"][~ism].mean()
                                    rows.append(row)
            print(inst, tf, "ok")
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(OUT, "confirm.csv"), index=False)
    paired_effects(res).to_csv(os.path.join(OUT, "confirm_effects.csv"), index=False)


if __name__ == "__main__":
    main()
