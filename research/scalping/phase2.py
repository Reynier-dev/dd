"""
Fase 2 — Brackets y órdenes límite para los gatillos con ventaja BRUTA.

Candidatos: configuraciones (mercado, TF, gatillo, lado, filtros) con t-stat bruto >= 5 en
descubrimiento y >= 2 en validación (results/gross_candidates.csv, ver scan.py). Por cada
(mercado, TF, gatillo, lado) se toman los 5 conjuntos de filtros con más t bruto.

Cada candidato se simula con la trayectoria de 1 minuto (sim.py) en:
  - 3 ejecuciones: mercado, límite al cierre de la señal, límite 0,25 ATR mejor
  - 4 stops (0,5 / 1 / 1,5 / 2 ATR) x 5 objetivos (0,5 / 1 / 1,5 / 2 / 3 ATR)
  - salida por tiempo a las 24 velas del TF o al cierre de la sesión regular

Métrica: puntos netos por operación (comisión + deslizamiento incluidos) y t-stat agrupado por
día. Solo descubrimiento y validación; la reserva 2017-2020 no se toca.

Reglas de selección (fijadas antes de correr):
  1. Descubrimiento: >= 150 operaciones, neto > 0, t agrupado >= 3.
  2. Validación: >= 50 operaciones, neto > 0, t agrupado >= 2.
  3. La misma regla (TF, gatillo, lado, filtros, ejecución, stop, objetivo) con neto > 0 en
     validación en al menos 2 de los 3 índices.
"""
import os
import time

import numpy as np
import pandas as pd

from features import cached_features
from recheck import events
from signals import filters, triggers
from sim import Minute, simulate

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
STOPS = (0.5, 1.0, 1.5, 2.0)
TARGETS = (0.5, 1.0, 1.5, 2.0, 3.0)
EXECS = (("mercado", 0, 0.0), ("límite", 1, 0.0), ("límite 0,25 ATR", 1, 0.25))
MAX_BARS = 24


def clustered(trades, day):
    x = trades["pts"].to_numpy()
    if len(x) < 3:
        return np.nan, np.nan
    s = pd.Series(x).groupby(day).agg(["sum", "count"])
    m = x.mean()
    var = ((s["sum"] - s["count"] * m) ** 2).sum() / len(x) ** 2
    return m, (m / np.sqrt(var) if var > 0 else np.nan)


def candidates():
    c = pd.read_csv(os.path.join(OUT, "gross_candidates.csv"))
    c["f2"] = c["f2"].fillna("")
    c = c.sort_values("tg_d", ascending=False).drop_duplicates(["inst", "tf", "trigger", "side", "f1", "f2"])
    return c.groupby(["inst", "tf", "trigger", "side"]).head(5)


def evaluate(configs, all_markets=False):
    rows = []
    for inst in configs["inst"].unique():
        minute = Minute(inst)
        for tf in configs.loc[configs.inst == inst, "tf"].unique():
            f = cached_features(inst, tf)
            trig, filt = triggers(f), filters(f)
            period = f["period"].astype(str).to_numpy()
            g = configs[(configs.inst == inst) & (configs.tf == tf)]
            t0 = time.time()
            for _, r in g.iterrows():
                m = events(f, trig, filt, r.trigger, r.side, r.f1, r.f2) & f["signal_ok"].to_numpy(bool)
                d = 1 if r.side == "Largo" else -1
                for p in ("descubrimiento", "validacion"):
                    sig = np.flatnonzero(m & (period == p))
                    if len(sig) < 20:
                        continue
                    for ex_name, mode, off in EXECS:
                        for sm in STOPS:
                            for tm in TARGETS:
                                tr = simulate(minute, f, tf, sig, d, sm, tm, MAX_BARS, mode=mode, offset=off)
                                day = tr["entry_time"].dt.normalize().to_numpy()
                                mean, tcl = clustered(tr, day)
                                rows.append(dict(inst=inst, tf=tf, trigger=r.trigger, side=r.side, f1=r.f1, f2=r.f2,
                                                 exec=ex_name, stop=sm, target=tm, period=p, n=len(tr),
                                                 net_pts=mean, t_clu=tcl,
                                                 net_R=(tr["pts"] / tr["risk_pts"]).mean() if len(tr) else np.nan,
                                                 win=(tr["pts"] > 0).mean() * 100 if len(tr) else np.nan))
            print(f"{inst} {tf}: {len(g)} configuraciones en {time.time() - t0:.0f}s", flush=True)
    return pd.DataFrame(rows)


def _evaluate_market(args):
    inst, configs = args
    return evaluate(configs[configs.inst == inst])


def main():
    from multiprocessing import Pool
    os.makedirs(OUT, exist_ok=True)
    c = candidates()
    rules = c[["tf", "trigger", "side", "f1", "f2"]].drop_duplicates()
    markets = ("NAS100_USD", "SPX500_USD", "US2000_USD")
    configs = pd.concat([rules.assign(inst=m) for m in markets], ignore_index=True)
    print(f"reglas candidatas: {len(rules)} | configuraciones (x 3 mercados): {len(configs)}", flush=True)
    with Pool(3) as pool:
        parts = pool.map(_evaluate_market, [(m, configs) for m in markets])
    res = pd.concat(parts, ignore_index=True)
    res.to_csv(os.path.join(OUT, "phase2.csv.gz"), index=False)

    key = ["inst", "tf", "trigger", "side", "f1", "f2", "exec", "stop", "target"]
    d = res[res.period == "descubrimiento"].set_index(key)
    v = res[res.period == "validacion"].set_index(key)
    j = d.join(v, lsuffix="_d", rsuffix="_v", how="inner").reset_index()
    s1 = j[(j.n_d >= 150) & (j.net_pts_d > 0) & (j.t_clu_d >= 3)]
    s2 = s1[(s1.n_v >= 50) & (s1.net_pts_v > 0) & (s1.t_clu_v >= 2)]
    rule = ["tf", "trigger", "side", "f1", "f2", "exec", "stop", "target"]
    pos = j.assign(pos=j.net_pts_v > 0).groupby(rule).pos.sum().rename("mercados_pos_validacion")
    s3 = s2.join(pos, on=rule)
    s3 = s3[s3.mercados_pos_validacion >= 2]
    j.to_csv(os.path.join(OUT, "phase2_joined.csv.gz"), index=False)
    s3.to_csv(os.path.join(OUT, "phase2_survivors.csv"), index=False)
    print(f"simulaciones: {len(j):,} | pasan descubrimiento: {len(s1)} | + validación: {len(s2)} | "
          f"+ 2 de 3 mercados: {len(s3)}", flush=True)


if __name__ == "__main__":
    main()
