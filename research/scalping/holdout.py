"""
Fase 3 — Evaluación única en el período de RESERVA (2017-2020) de los finalistas
pre-registrados en finalists.json (el archivo se versiona en git antes de correr esto).

Cada finalista se evalúa en los 3 índices con exactamente la misma regla, ejecución y bracket
elegidos con los datos de 2008-2016.

Salida: results/holdout.csv, results/holdout_trades.csv
"""
import json
import os

import numpy as np
import pandas as pd

from features import cached_features
from phase2 import MAX_BARS, clustered
from recheck import events
from signals import filters, triggers
from sim import Minute, simulate

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
EXEC_MODE = {"mercado": (0, 0.0), "límite": (1, 0.0), "límite 0,25 ATR": (1, 0.25)}
MARKETS = ("NAS100_USD", "SPX500_USD", "US2000_USD")


def main():
    with open(os.path.join(HERE, "finalists.json"), encoding="utf-8") as fh:
        finalists = json.load(fh)["finalistas"]
    rows, trades = [], []
    for inst in MARKETS:
        minute = Minute(inst)
        for tf in sorted({x["tf"] for x in finalists}):
            f = cached_features(inst, tf)
            trig, filt = triggers(f), filters(f)
            period = f["period"].astype(str).to_numpy()
            for k, x in enumerate(finalists):
                if x["tf"] != tf:
                    continue
                m = events(f, trig, filt, x["trigger"], x["side"], x["f1"], x["f2"]) & f["signal_ok"].to_numpy(bool)
                d = 1 if x["side"] == "Largo" else -1
                mode, off = EXEC_MODE[x["exec"]]
                for p in ("descubrimiento", "validacion", "reserva"):
                    sig = np.flatnonzero(m & (period == p))
                    tr = simulate(minute, f, tf, sig, d, x["stop"], x["target"], MAX_BARS, mode=mode, offset=off)
                    mean, tcl = clustered(tr, tr["entry_time"].dt.normalize().to_numpy())
                    rows.append(dict(finalista=k + 1, inst=inst, period=p, n=len(tr), net_pts=mean, t_clu=tcl,
                                     net_R=(tr["pts"] / tr["risk_pts"]).mean() if len(tr) else np.nan,
                                     win=(tr["pts"] > 0).mean() * 100 if len(tr) else np.nan,
                                     usd_per_trade=mean * {"NAS100_USD": 20, "SPX500_USD": 50, "US2000_USD": 50}[inst],
                                     **{kk: x[kk] for kk in ("tf", "trigger", "side", "f1", "f2", "exec", "stop", "target")}))
                    if p == "reserva":
                        trades.append(tr.assign(finalista=k + 1, inst=inst))
        print(inst, "ok", flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "holdout.csv"), index=False)
    if trades:
        pd.concat(trades).to_csv(os.path.join(OUT, "holdout_trades.csv"), index=False)


if __name__ == "__main__":
    main()
