"""
Parte E — Swing diario: RSI(2) extremo a favor de la EMA 200 (variante de L. Connors).

Regla base (fijada en la Parte B, antes de esta rejilla):
  Largo cuando el RSI(2) diario cierra < 10 con el cierre sobre la EMA 200.
  Salida cuando el cierre supera la EMA 5. Stop de protección 2 ATR(14). Máximo 20 sesiones.
  Entrada y salida en la apertura de la sesión siguiente.

Pruebas:
  1. Rejilla: umbral RSI(2) 5-25, filtro EMA 100/200/sin filtro, salida EMA5 o RSI(2) > 70,
     stop 2 ATR / 3 ATR / sin stop.
  2. Control: entradas aleatorias con el mismo filtro de tendencia y la misma salida.
  3. Ejecución alternativa: entrar al cierre de la señal (orden MOC) en vez de la apertura.

Salida: results/swing_grid.csv, results/swing_control.csv, results/swing_trades.csv
"""
import os

import numpy as np
import pandas as pd

from lib import COST_PTS, NAMES, add_indicators, ema, load, metrics, simulate, years_span
from study_setups import in_sample

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
BASE = dict(thr=10, trend="EMA 200", exit="cierre > EMA 5", stop=2.0)


def trend_mask(df, trend):
    if trend == "sin filtro":
        return np.ones(len(df), bool)
    return (df["close"] > df[f"ema{trend.split()[1]}"]).values


def exit_mask(df, kind):
    if kind == "cierre > EMA 5":
        return (df["close"] > df["ema5"]).values
    return (df["rsi2"] > 70).values


def simulate_at_close(df, entry, exit_sig, stop_mult, max_bars, cost):
    """Variante MOC: se entra al CIERRE de la vela de señal (el resto igual que lib.simulate)."""
    shifted = df.copy()
    shifted["open"] = df["close"].shift(1).fillna(df["open"])  # la "apertura" de i+1 pasa a ser el cierre de i
    return simulate(shifted, entry, exit_sig, np.zeros(len(df), bool), 1, stop_mult, 0.0, max_bars, cost)


def main():
    os.makedirs(OUT, exist_ok=True)
    grid, ctrl, trades = [], [], []
    rng = np.random.default_rng(7)
    for inst in NAMES:
        raw = load(inst, "1d")
        df = add_indicators(raw)
        df["ema100"] = ema(raw["close"], 100).reindex(df.index)  # calculada sobre toda la historia
        cost = COST_PTS[inst]
        yrs = years_span(df.index)
        none = np.zeros(len(df), bool)
        for thr in (5, 10, 15, 20, 25):
            for trend in ("EMA 200", "EMA 100", "sin filtro"):
                for ex in ("cierre > EMA 5", "RSI(2) > 70"):
                    for stop in (2.0, 3.0, 50.0):
                        ent = (df["rsi2"] < thr).values & trend_mask(df, trend)
                        tr = simulate(df, ent, exit_mask(df, ex), none, 1, stop, 0.0, 20, cost)
                        ism = in_sample(tr["entry_time"])
                        row = dict(inst=inst, thr=thr, trend=trend, exit=ex, stop="sin stop" if stop > 10 else f"{stop:g} ATR")
                        row.update(metrics(tr, yrs))
                        row["IS_avgR"], row["OOS_avgR"] = tr["R"][ism].mean(), tr["R"][~ism].mean()
                        grid.append(row)

        b = BASE
        ent = (df["rsi2"] < b["thr"]).values & trend_mask(df, b["trend"])
        ex = exit_mask(df, b["exit"])
        tr = simulate(df, ent, ex, none, 1, b["stop"], 0.0, 20, cost)
        trades.append(tr.assign(inst=inst))
        moc = simulate_at_close(df, ent, ex, b["stop"], 20, cost)
        ok = trend_mask(df, b["trend"])
        p = len(tr) / max(ok.sum(), 1) * 3
        rand = [simulate(df, ok & (rng.random(len(df)) < p), ex, none, 1, b["stop"], 0.0, 20, cost)["R"].mean()
                for _ in range(200)]
        ism = in_sample(tr["entry_time"])
        m = metrics(tr, yrs)
        ctrl.append(dict(inst=inst, trades=len(tr), per_year=m["per_year"], win=m["win"], avgR=m["avgR"], PF=m["PF"],
                         t=m["t"], maxDD_R=m["maxDD_R"], bars=m["bars"],
                         IS_avgR=tr["R"][ism].mean(), OOS_avgR=tr["R"][~ism].mean(),
                         pct_pts=(tr["pts"] / df["close"].reindex(tr["entry_time"]).values * 100).mean(),
                         moc_avgR=moc["R"].mean(), random_avgR=np.mean(rand),
                         pct_random_better=(np.array(rand) >= tr["R"].mean()).mean() * 100))
        print(inst, "ok")
    pd.DataFrame(grid).to_csv(os.path.join(OUT, "swing_grid.csv"), index=False)
    pd.DataFrame(ctrl).to_csv(os.path.join(OUT, "swing_control.csv"), index=False)
    pd.concat(trades).to_csv(os.path.join(OUT, "swing_trades.csv"), index=False)


if __name__ == "__main__":
    main()
