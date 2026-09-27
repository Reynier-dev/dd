"""
Fase 5 — ¿Alcanzaría la ventaja bruta con los costos relativos de hoy?

El costo por operación es fijo en ticks, pero el tamaño de las velas crece con el precio. En NQ 1m
el costo pasó de ~0,6 ATR en 2009-2013 a ~0,2 ATR en 2018-2019 (results/cost_by_year.csv).
Esta fase mide la ventaja BRUTA de cada combinación en unidades de ATR (independiente del nivel
de precio) usando solo 2008-2016, y selecciona mecánicamente las que superarían el costo de NQ
en 2018-2019.

Pasos (fijados antes de correr):
  1. Escaneo en ATR, sin costos, descubrimiento y validación (misma rejilla que scan.py).
  2. Pre-filtro: >= 300 eventos en descubrimiento, bruto > 0, t ingenuo >= 4; se recalculan las
     300 de mayor t con errores agrupados por día (recheck).
  3. Selección: t agrupado >= 3 en descubrimiento y >= 2 en validación, bruto > 0 en ambos, bruto
     > 0 en validación en al menos 2 de los 3 índices, y bruto medio (desc. y valid.) mayor que el
     costo de NQ 2018-2019 en ATR para ese timeframe.
  4. Las 10 de mayor t agrupado mínimo (entre desc. y valid.) se registran en
     finalists_phase5.json ANTES de evaluar 2017-2020 (holdout_phase5.py).

Salida: results/phase5_scan.csv.gz, results/phase5_recheck.csv, results/phase5_selected.csv
"""
import os
import time

import numpy as np
import pandas as pd

from features import INSTRUMENTS, TF_MIN, cached_features
from recheck import events
from scan import HORIZONS, PERIODS, combos, forward_points
from signals import filters, triggers

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")


def forward_atr(f, h):
    return forward_points(f, h) / f["atr"].to_numpy(np.float64)


def scan_one(inst, tf):
    f = cached_features(inst, tf)
    trig, filt = triggers(f), filters(f)
    fnames = list(filt) + ["(ninguna)"]
    pairs = combos(fnames)
    period = f["period"].astype(str).to_numpy()
    fwd = np.stack([forward_atr(f, h) for h in HORIZONS], axis=1)
    valid = np.isin(period, PERIODS) & np.isfinite(fwd).all(axis=1)
    rows = []
    for side_i, (side, d) in enumerate((("Largo", 1.0), ("Corto", -1.0))):
        F = np.stack([filt[k][side_i] for k in filt] + [np.ones(len(f), bool)], axis=1)
        for tname, tv in trig.items():
            ev = np.flatnonzero(tv[side_i] & valid)
            if len(ev) < 50:
                continue
            E = F[ev].astype(np.float64)
            R = d * fwd[ev]
            st = {}
            for p in PERIODS:
                w = (period[ev] == p).astype(np.float64)
                N = E.T @ (E * w[:, None])
                S1 = [E.T @ (E * (w * R[:, j])[:, None]) for j in range(len(HORIZONS))]
                S2 = [E.T @ (E * (w * R[:, j] ** 2)[:, None]) for j in range(len(HORIZONS))]
                st[p] = (N, S1, S2)
            for a, b in pairs:
                if st["descubrimiento"][0][a, b] < 300:
                    continue
                fa = fnames[a]
                fb = fnames[b] if b != len(fnames) - 1 else ""
                for j, h in enumerate(HORIZONS):
                    row = dict(inst=inst, tf=tf, trigger=tname, side=side, f1=fa, f2=fb, h=h)
                    for p, tag in zip(PERIODS, ("d", "v")):
                        N, S1, S2 = st[p]
                        n = N[a, b]
                        mean = S1[j][a, b] / n if n > 0 else np.nan
                        sd = np.sqrt(max(S2[j][a, b] / n - mean ** 2, 1e-12)) if n > 1 else np.nan
                        row[f"n_{tag}"], row[f"gross_atr_{tag}"] = int(n), mean
                        row[f"t_{tag}"] = mean / sd * np.sqrt(n) if n > 1 else np.nan
                    rows.append(row)
    return rows


def recheck_atr(cands):
    out = []
    for (inst, tf), g in cands.groupby(["inst", "tf"]):
        f = cached_features(inst, tf)
        trig, filt = triggers(f), filters(f)
        period = f["period"].astype(str).to_numpy()
        day = f["date"].to_numpy()
        fwd = {h: forward_atr(f, h) for h in HORIZONS}
        for _, r in g.iterrows():
            d = 1.0 if r.side == "Largo" else -1.0
            m = events(f, trig, filt, r.trigger, r.side, r.f1, r.f2) & np.isfinite(fwd[r.h])
            row = r.to_dict()
            for p, tag in (("descubrimiento", "d"), ("validacion", "v")):
                ev = np.flatnonzero(m & (period == p))
                x = d * fwd[r.h][ev]
                s = pd.Series(x).groupby(day[ev]).agg(["sum", "count"])
                mean = x.mean() if len(x) else np.nan
                var = ((s["sum"] - s["count"] * mean) ** 2).sum() / len(x) ** 2 if len(x) else np.nan
                row[f"tclu_{tag}"] = mean / np.sqrt(var) if var and var > 0 else np.nan
            out.append(row)
    return pd.DataFrame(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for inst in INSTRUMENTS:
        for tf in TF_MIN:
            t0 = time.time()
            rows += scan_one(inst, tf)
            print(f"{inst} {tf} {time.time() - t0:.0f}s", flush=True)
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(OUT, "phase5_scan.csv.gz"), index=False)

    pre = res[(res.gross_atr_d > 0) & (res.t_d >= 4)].sort_values("t_d", ascending=False).head(300)
    rc = recheck_atr(pre)
    rc.to_csv(os.path.join(OUT, "phase5_recheck.csv"), index=False)

    cost = pd.read_csv(os.path.join(OUT, "cost_by_year.csv"))
    nq = cost[(cost.inst == "NAS100_USD") & cost.year.isin([2018, 2019])].groupby("tf").cost_atr.mean()
    key = ["tf", "trigger", "side", "f1", "f2", "h"]
    pos_v = res.assign(pos=res.gross_atr_v > 0).groupby(key).pos.sum().rename("mercados_pos_validacion")
    s = rc.join(pos_v, on=key)
    s["cost_nq_2018_19"] = s.tf.map(nq)
    s["gross_mean"] = s[["gross_atr_d", "gross_atr_v"]].mean(axis=1)
    sel = s[(s.tclu_d >= 3) & (s.tclu_v >= 2) & (s.gross_atr_d > 0) & (s.gross_atr_v > 0)
            & (s.mercados_pos_validacion >= 2) & (s.gross_mean > s.cost_nq_2018_19)].copy()
    sel["score"] = sel[["tclu_d", "tclu_v"]].min(axis=1)
    sel = sel.sort_values("score", ascending=False)
    sel.to_csv(os.path.join(OUT, "phase5_selected.csv"), index=False)
    print(f"combinaciones: {len(res):,} | pre-filtro: {len(pre)} | seleccionadas: {len(sel)}")
    print("costo NQ 2018-2019 en ATR:", nq.round(3).to_dict())


if __name__ == "__main__":
    main()
