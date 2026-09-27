"""
Parte A — ¿Qué relación estadística hay entre EMAs, RSI y el movimiento FUTURO del precio?

Para cada instrumento y timeframe calcula:
  1. Matriz de correlación (Spearman) entre los propios indicadores -> redundancia.
  2. IC (Information Coefficient): correlación de Spearman entre cada indicador y el
     retorno futuro a h barras, medido en ATRs (comparable entre años y mercados).
  3. Tabla condicional: retorno futuro medio por tramo de RSI(14) dentro de cada
     régimen de tendencia definido por EMAs (Alcista / Neutral / Bajista).

En intradía (5m, 15m) solo se usan barras de la sesión regular (RTH) y el horizonte
futuro no puede cruzar el cierre de las 16:00 ET.

Salida: results/ic.csv, results/feature_corr.csv, results/rsi_regime.csv
"""
import os

import numpy as np
import pandas as pd

from lib import NAMES, add_indicators, load

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
TFS = ["5m", "15m", "1h", "1d"]
HORIZONS = {"5m": [1, 6, 12], "15m": [1, 4, 8], "1h": [1, 6, 24], "1d": [1, 5, 10]}
FEATURES = ["rsi2", "rsi14", "d21", "d50", "d200", "slope21", "gap_9_21"]
RSI_BINS = [0, 20, 30, 40, 50, 60, 70, 80, 100]


def forward_returns(df, tf, h):
    fwd = (df["close"].shift(-h) - df["close"]) / df["atr"]
    if tf in ("5m", "15m"):
        t = df.index
        minutes = t.hour * 60 + t.minute
        rth = pd.Series((minutes >= 570) & (minutes < 960), index=t)
        day = pd.Series(t.normalize(), index=t)
        ok = rth & rth.shift(-h, fill_value=False) & (day == day.shift(-h))
        fwd = fwd.where(ok)
    return fwd


def main():
    os.makedirs(OUT, exist_ok=True)
    ic_rows, corr_rows, cond_rows = [], [], []
    for inst in NAMES:
        for tf in TFS:
            df = add_indicators(load(inst, tf))
            hs = HORIZONS[tf]
            for h in hs:
                df[f"f{h}"] = forward_returns(df, tf, h)
            base = df.dropna(subset=[f"f{hs[-1]}"])
            ranks = base[FEATURES + [f"f{h}" for h in hs]].rank()

            # 1) Redundancia entre indicadores
            fc = ranks[FEATURES].corr()
            for a in FEATURES:
                for b in FEATURES:
                    corr_rows.append(dict(inst=inst, tf=tf, a=a, b=b, rho=fc.loc[a, b]))

            # 2) IC de cada indicador contra el retorno futuro, total y dentro de cada régimen
            for reg in ["Todos", "Alcista", "Neutral", "Bajista"]:
                sub = ranks if reg == "Todos" else base[base["regime"] == reg][FEATURES + [f"f{h}" for h in hs]].rank()
                for h in hs:
                    for f in FEATURES:
                        ic_rows.append(dict(inst=inst, tf=tf, regime=reg, h=h, feature=f,
                                            ic=sub[f].corr(sub[f"f{h}"]), n=len(sub)))

            # 3) Tabla RSI x régimen (horizonte intermedio)
            h = hs[1]
            drift = base[f"f{h}"].mean()
            b = base.assign(rsi_bin=pd.cut(base["rsi14"], RSI_BINS, include_lowest=True))
            g = b.groupby(["regime", "rsi_bin"], observed=True)[f"f{h}"]
            tab = pd.DataFrame({"mean": g.mean(), "up": g.apply(lambda s: (s > 0).mean() * 100),
                                "n": g.size()}).reset_index()
            tab["edge"] = tab["mean"] - drift
            tab["t"] = tab["edge"] / (g.std().values / np.sqrt(tab["n"]))
            tab["inst"], tab["tf"], tab["h"], tab["drift"] = inst, tf, h, drift
            cond_rows.append(tab)
            print(f"{inst:11s} {tf:>3s}  n={len(base):,}")

    pd.DataFrame(ic_rows).to_csv(os.path.join(OUT, "ic.csv"), index=False)
    pd.DataFrame(corr_rows).to_csv(os.path.join(OUT, "feature_corr.csv"), index=False)
    cond = pd.concat(cond_rows, ignore_index=True)
    cond["rsi_bin"] = cond["rsi_bin"].astype(str)
    cond.to_csv(os.path.join(OUT, "rsi_regime.csv"), index=False)


if __name__ == "__main__":
    main()
