"""
Parte D — Robustez del sistema "semáforo + RSI" en 15m.

Regla: operar solo a favor del régimen EMA de 1h y del diario; entrar cuando el RSI(14)
de 15m sale de la zona extrema (cruza hacia arriba L en largos, hacia abajo 100-L en
cortos); salir cuando el RSI llega a X (100-X en cortos), stop de S ATR o a las 16:00 ET.

Se barre una rejilla de parámetros para ver si la ventaja es estable (no un pico
aislado) y se compara contra un CONTROL: entradas aleatorias con el mismo filtro y la
misma frecuencia de operaciones. Si el RSI no aportara nada, ambos darían igual.

Salida: results/robust_grid.csv, results/robust_control.csv, results/system_trades.csv
"""
import os

import numpy as np
import pandas as pd

from lib import COST_PTS, NAMES, add_indicators, load, metrics, session_masks, simulate, years_span
from study_mtf import attach_htf
from study_setups import cross_dn, cross_up, in_sample

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
FILTERS = ("1h", "1d", "1h+1d")
BASE = dict(L=30, X=50, S=2.0, filt="1h+1d")  # la versión "de libro", fijada antes de ver la rejilla


def filters(df, filt, d):
    if filt == "1h":
        return (df["regime_1h"] == d).values
    if filt == "1d":
        return (df["regime_1d"] == d).values
    return ((df["regime_1h"] == d) & (df["regime_1d"] == d)).values


def signals(df, L, X, d):
    r = df["rsi14"]
    if d == 1:
        return cross_up(r, L).fillna(False).values, (r > X).values
    return cross_dn(r, 100 - L).fillna(False).values, (r < 100 - X).values


def run(df, inst, L, X, S, filt, d, allow, force):
    ent, ex = signals(df, L, X, d)
    ent = ent & allow & filters(df, filt, d)
    return simulate(df, ent, ex, force, d, S, 0.0, 1000, COST_PTS[inst])


def main():
    os.makedirs(OUT, exist_ok=True)
    grid_rows, ctrl_rows, sys_trades = [], [], []
    rng = np.random.default_rng(42)
    for inst in NAMES:
        df = attach_htf(add_indicators(load(inst, "15m")), inst)
        allow, force = session_masks(df, "15m")
        yrs = years_span(df.index)
        for d, side in ((1, "Largo"), (-1, "Corto")):
            for filt in FILTERS:
                for L in (20, 25, 30, 35, 40):
                    for X in (50, 60, 70):
                        for S in (1.5, 2.0, 3.0):
                            tr = run(df, inst, L, X, S, filt, d, allow, force)
                            ism = in_sample(tr["entry_time"])
                            row = dict(inst=inst, side=side, filt=filt, L=L, X=X, S=S)
                            row.update(metrics(tr, yrs))
                            row["IS_avgR"], row["OOS_avgR"] = tr["R"][ism].mean(), tr["R"][~ism].mean()
                            grid_rows.append(row)

            # Control: misma salida y filtro, entradas aleatorias con la misma frecuencia
            b = BASE
            tr = run(df, inst, b["L"], b["X"], b["S"], b["filt"], d, allow, force)
            tr = tr.assign(inst=inst, side=side)
            sys_trades.append(tr)
            _, ex = signals(df, b["L"], b["X"], d)
            ok = allow & filters(df, b["filt"], d)
            p = len(tr) / max(ok.sum(), 1) * 3  # algo más de señales para compensar las que caen dentro de una operación
            rand = []
            for _ in range(50):
                e = ok & (rng.random(len(df)) < p)
                t2 = simulate(df, e, ex, force, d, b["S"], 0.0, 1000, COST_PTS[inst])
                rand.append(t2["R"].mean())
            ctrl_rows.append(dict(inst=inst, side=side, system_avgR=tr["R"].mean(), system_n=len(tr),
                                  random_avgR=np.mean(rand), random_p95=np.percentile(rand, 95),
                                  pct_random_better=(np.array(rand) >= tr["R"].mean()).mean() * 100))
        print(inst, "ok")
    pd.DataFrame(grid_rows).to_csv(os.path.join(OUT, "robust_grid.csv"), index=False)
    pd.DataFrame(ctrl_rows).to_csv(os.path.join(OUT, "robust_control.csv"), index=False)
    pd.concat(sys_trades).to_csv(os.path.join(OUT, "system_trades.csv"), index=False)


if __name__ == "__main__":
    main()
