"""
Evaluación única de los finalistas de la Fase 5 (finalists_phase5.json) en 2017-2020.

Entrada a mercado en la apertura de la vela siguiente a la señal y salida a mercado al cierre de h
velas (o a las 16:00), una operación a la vez, neto de comisión + 1 tick por lado.

Salida: results/holdout_phase5.csv
"""
import json
import os

import numpy as np
import pandas as pd

from features import COST_MARKET, INSTRUMENTS, POINT_VALUE, cached_features
from recheck import events
from scan import forward_points
from signals import filters, triggers

HERE = os.path.dirname(os.path.abspath(__file__))


def non_overlapping(ev, h):
    keep, nxt = [], -1
    for e in ev:
        if e >= nxt:
            keep.append(e)
            nxt = e + h
    return np.array(keep, dtype=int)


def main():
    with open(os.path.join(HERE, "finalists_phase5.json"), encoding="utf-8") as fh:
        fin = json.load(fh)["finalistas"]
    rows = []
    for inst in INSTRUMENTS:
        cache = {}
        for k, x in enumerate(fin):
            if x["tf"] not in cache:
                f = cached_features(inst, x["tf"])
                cache[x["tf"]] = (f, triggers(f), filters(f), f["period"].astype(str).to_numpy(), f["date"].to_numpy(),
                                  f["atr"].to_numpy(np.float64))
            f, trig, filt, period, day, atr = cache[x["tf"]]
            fwd = forward_points(f, x["h"])
            d = 1.0 if x["side"] == "Largo" else -1.0
            m = events(f, trig, filt, x["trigger"], x["side"], x["f1"], x["f2"]) & np.isfinite(fwd)
            for p in ("descubrimiento", "validacion", "reserva"):
                ev = non_overlapping(np.flatnonzero(m & (period == p)), x["h"])
                net = d * fwd[ev] - COST_MARKET[inst]
                s = pd.Series(net).groupby(day[ev]).agg(["sum", "count"])
                mu = net.mean() if len(net) else np.nan
                var = ((s["sum"] - s["count"] * mu) ** 2).sum() / len(net) ** 2 if len(net) else np.nan
                rows.append(dict(finalista=k + 1, inst=inst, period=p, n=len(net), net_pts=mu,
                                 t_clu=mu / np.sqrt(var) if var and var > 0 else np.nan,
                                 net_atr=(net / atr[ev]).mean() if len(net) else np.nan,
                                 cost_atr=(COST_MARKET[inst] / atr[ev]).mean() if len(net) else np.nan,
                                 win=(net > 0).mean() * 100 if len(net) else np.nan,
                                 usd_per_trade=mu * POINT_VALUE[inst],
                                 **{kk: x[kk] for kk in ("tf", "trigger", "side", "f1", "f2", "h")}))
        print(inst, "ok", flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(HERE, "results", "holdout_phase5.csv"), index=False)


if __name__ == "__main__":
    main()
