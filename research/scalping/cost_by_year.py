"""
El costo fijo (en ticks) frente al tamaño de las velas, año por año.

Para cada mercado y timeframe: ATR(14) mediano en horario regular y el costo de una operación
a mercado expresado en ATR. Con stop y objetivo de k ATR, el porcentaje de aciertos necesario
para empatar es (k + c) / (2k), con c = costo en ATR.

Salida: results/cost_by_year.csv
"""
import os

import pandas as pd

from features import COST_MARKET, INSTRUMENTS, TF_MIN, cached_features

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    rows = []
    for inst in INSTRUMENTS:
        for tf in TF_MIN:
            f = cached_features(inst, tf)[["atr", "close", "rth"]]
            f = f[f["rth"]]
            g = f.groupby(f.index.year)
            for y, x in g:
                atr = x["atr"].median()
                c = COST_MARKET[inst] / atr
                rows.append(dict(inst=inst, tf=tf, year=y, price=x["close"].median(), atr_pts=atr, cost_atr=c,
                                 breakeven_win_1to1=(1 + c) / 2 * 100))
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(HERE, "results", "cost_by_year.csv"), index=False)
    p = out.pivot_table(index="year", columns=["inst", "tf"], values="cost_atr").round(2)
    print(p.to_string())


if __name__ == "__main__":
    main()
