"""
Parte F — Cuánto engaña un error de look-ahead de 1 hora.

Corre el sistema intradía "semáforo 1h+1d + RSI(14) 30/70 en 15m" dos veces:
  - correcto: cada vela de 15m ve la última barra de 1h YA CERRADA.
  - con error: se asigna la barra de 1h que todavía se está formando (lo que pasa en pandas
    si se construye un DataFrame con una Series y un índice desplazado: realinea por etiqueta
    en vez de re-etiquetar). Es el error que tuvo la primera versión de este estudio.

Salida: results/lookahead.csv
"""
import os

import pandas as pd

from lib import NAMES, add_indicators, load, session_masks
from study_mtf import REG, attach_htf
from study_robust import run

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")


def attach_htf_with_lookahead(df15, inst):
    df = attach_htf(df15, inst)
    h1 = add_indicators(load(inst, "1h"))
    wrong = pd.DataFrame({"regime_1h": h1["regime"].map(REG)}, index=h1.index + pd.Timedelta(hours=1))  # el error
    end = pd.Series(df.index + pd.Timedelta(minutes=15), index=df.index, name="end")
    m = pd.merge_asof(end.to_frame(), wrong, left_on="end", right_index=True, direction="backward")
    df["regime_1h"] = m["regime_1h"].values
    return df


def main():
    rows = []
    for inst in NAMES:
        base = add_indicators(load(inst, "15m"))
        for label, df in (("correcto", attach_htf(base, inst)), ("con look-ahead de 1h", attach_htf_with_lookahead(base, inst))):
            allow, force = session_masks(df, "15m")
            trs = [run(df, inst, 30, 50, 2.0, "1h+1d", d, allow, force) for d in (1, -1)]
            tr = pd.concat(trs)
            rows.append(dict(inst=inst, version=label, trades=len(tr), avgR=tr["R"].mean(), totR=tr["R"].sum()))
        print(inst, "ok")
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "lookahead.csv"), index=False)


if __name__ == "__main__":
    main()
