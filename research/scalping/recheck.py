"""
Fase 1b — Recalcula los candidatos del escaneo corrigiendo el solapamiento.

El escaneo trata cada vela como una prueba independiente. Pero las velas consecutivas de un
mismo día comparten gran parte del recorrido (con h = 24 velas, dos señales seguidas tienen 23
velas en común), y eso infla el t-stat. Aquí, para cada candidato:
  - t agrupado por día: la varianza se estima con las sumas diarias (errores "cluster").
  - sin solapamiento: se toma una señal y se ignoran las siguientes hasta que termine su horizonte.
"""
import numpy as np
import pandas as pd

from features import COST_MARKET, cached_features
from scan import HORIZONS, forward_points
from signals import filters, triggers


def events(f, trig, filt, tname, side, f1, f2):
    si = 0 if side == "Largo" else 1
    if tname.startswith("Control"):
        m = np.ones(len(f), bool)
    else:
        m = trig[tname][si].copy()
    for fn in (f1, f2):
        if isinstance(fn, str) and fn and fn != "(ninguna)":
            m &= filt[fn][si]
    return m


def recheck(cands):
    out = []
    for (inst, tf), g in cands.groupby(["inst", "tf"]):
        f = cached_features(inst, tf)
        trig, filt = triggers(f), filters(f)
        period = f["period"].astype(str).to_numpy()
        day = f["date"].to_numpy()
        cost = COST_MARKET[inst]
        fwd = {h: forward_points(f, h) for h in HORIZONS}
        for _, r in g.iterrows():
            d = 1.0 if r.side == "Largo" else -1.0
            m = events(f, trig, filt, r.trigger, r.side, r.f1, r.f2) & np.isfinite(fwd[r.h])
            row = r.to_dict()
            for p, tag in (("descubrimiento", "d"), ("validacion", "v")):
                ev = np.flatnonzero(m & (period == p))
                x = d * fwd[r.h][ev] - cost
                # errores agrupados por día
                s = pd.Series(x).groupby(day[ev]).agg(["sum", "count"])
                mean = x.mean() if len(x) else np.nan
                var = ((s["sum"] - s["count"] * mean) ** 2).sum() / len(x) ** 2 if len(x) else np.nan
                row[f"days_{tag}"] = len(s)
                row[f"tclu_{tag}"] = mean / np.sqrt(var) if var and var > 0 else np.nan
                # sin solapamiento
                keep, nxt = [], -1
                for e in ev:
                    if e >= nxt:
                        keep.append(e)
                        nxt = e + r.h
                y = d * fwd[r.h][np.array(keep, dtype=int)] - cost if keep else np.array([])
                row[f"nov_n_{tag}"] = len(y)
                row[f"nov_net_{tag}"] = y.mean() if len(y) else np.nan
                row[f"nov_t_{tag}"] = y.mean() / y.std(ddof=1) * np.sqrt(len(y)) if len(y) > 2 else np.nan
            out.append(row)
    return pd.DataFrame(out)


if __name__ == "__main__":
    r = pd.read_csv("results/scan.csv.gz")
    cands = r[(r.n_d >= 300) & (r.net_d > 0) & (r.t_d >= 3)]
    res = recheck(cands)
    res.to_csv("results/scan_recheck.csv", index=False)
    ok = res[(res.tclu_d >= 3) & (res.nov_t_d >= 2.5) & (res.nov_n_d >= 150)
             & (res.tclu_v >= 2) & (res.nov_net_v > 0)]
    ok.to_csv("results/scan_recheck_survivors.csv", index=False)
    print(f"candidatos: {len(res)} | sobreviven con t agrupado por día y sin solapamiento: {len(ok)}")
