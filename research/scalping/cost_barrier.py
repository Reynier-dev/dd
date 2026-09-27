"""
La barrera de costos: resultado de entradas AL AZAR (sin ninguna ventaja) con bracket 1:1 de
1 ATR, por mercado, timeframe y tipo de ejecución. Es lo que una regla tiene que superar solo
para quedar en cero. Período de descubrimiento, 20.000 entradas por celda.

Salida: results/cost_barrier.csv
"""
import os

import numpy as np
import pandas as pd

from features import INSTRUMENTS, TF_MIN, cached_features
from sim import Minute, simulate

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    rng = np.random.default_rng(11)
    rows = []
    for inst in INSTRUMENTS:
        minute = Minute(inst)
        for tf in TF_MIN:
            f = cached_features(inst, tf)
            ok = np.flatnonzero(f["signal_ok"].to_numpy(bool) & (f["period"].astype(str).to_numpy() == "descubrimiento"))
            sig = np.sort(rng.choice(ok, min(20000, len(ok)), replace=False))
            for ex, mode, off in (("mercado", 0, 0.0), ("límite", 1, 0.0)):
                res = [simulate(minute, f, tf, sig, d, 1.0, 1.0, 24, mode=mode, offset=off) for d in (1, -1)]
                tr = pd.concat(res)
                rows.append(dict(inst=inst, tf=tf, exec=ex, n=len(tr), atr_pts=f["atr"].to_numpy()[sig].mean(),
                                 net_pts=tr["pts"].mean(), net_R=(tr["pts"] / tr["risk_pts"]).mean(),
                                 win=(tr["pts"] > 0).mean() * 100))
            print(inst, tf, flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(HERE, "results", "cost_barrier.csv"), index=False)
    print(out.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
