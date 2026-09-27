"""
Fase 1 — Escaneo masivo de gatillos × confirmaciones (estudio de eventos).

Para cada mercado (NQ, ES, RTY), timeframe (1m, 3m, 5m), gatillo (27 + control "cualquier
vela"), lado y conjunto de confirmaciones (ninguna, 1 o 2 de 18 filtros = 172 conjuntos) se
mide el resultado de entrar A MERCADO en la apertura de la vela siguiente y salir al cierre
de h velas después (h = 3, 6, 12, 24), cortando en el cierre de la sesión regular.

Resultado en PUNTOS de futuro, neto de costos (comisión + 1 tick por lado).

Solo se calculan los períodos de DESCUBRIMIENTO (2008-2013) y VALIDACIÓN (2014-2016).
El período de reserva (2017-2020) no se toca en esta fase.

Reglas de selección (fijadas antes de correr el escaneo):
  1. Descubrimiento: >= 300 operaciones, neto medio > 0 y t-stat neto >= 3.
  2. Validación, misma configuración y mercado: >= 100 operaciones, neto > 0 y t-stat >= 2.
  3. Validación en los otros índices: neto > 0 en al menos 2 de los 3 mercados.

Salida: results/scan.csv.gz (todas las combinaciones), results/scan_survivors.csv
"""
import os
import time

import numpy as np
import pandas as pd

from features import COST_MARKET, INSTRUMENTS, TF_MIN, cached_features
from signals import filters, triggers

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
HORIZONS = (3, 6, 12, 24)
PERIODS = ("descubrimiento", "validacion")


def forward_points(f, h):
    """Entrada en la apertura de i+1, salida al cierre de min(i+h, última vela RTH del día)."""
    n = len(f)
    o = f["open"].to_numpy(np.float64)
    c = f["close"].to_numpy(np.float64)
    last = f["last_rth_pos"].to_numpy()
    idx = np.arange(n)
    exit_i = np.minimum(idx + h, np.where(last >= 0, last, idx))
    entry_i = np.minimum(idx + 1, n - 1)
    ok = f["signal_ok"].to_numpy(bool) & (last > idx)
    return np.where(ok, c[exit_i] - o[entry_i], np.nan)


def combos(names):
    k = len(names)  # la última columna es "ninguna" (unos)
    out = []
    for a in range(k):
        for b in range(a, k):
            if a == b and a != k - 1:
                continue
            out.append((a, b))
    return out


def scan_one(inst, tf):
    f = cached_features(inst, tf)
    trig = triggers(f)
    trig["Control: cualquier vela"] = (np.ones(len(f), bool), np.ones(len(f), bool))
    filt = filters(f)
    fnames = list(filt) + ["(ninguna)"]
    pairs = combos(fnames)
    period = f["period"].astype(str).to_numpy()
    in_scope = np.isin(period, PERIODS)
    fwd = np.stack([forward_points(f, h) for h in HORIZONS], axis=1)
    valid = in_scope & np.isfinite(fwd).all(axis=1)
    cost = COST_MARKET[inst]
    rows = []
    for side_i, (side, d) in enumerate((("Largo", 1.0), ("Corto", -1.0))):
        F = np.stack([filt[k][side_i] for k in filt] + [np.ones(len(f), bool)], axis=1)
        for tname, tv in trig.items():
            ev = np.flatnonzero(tv[side_i] & valid)
            if len(ev) < 50:
                continue
            E = F[ev].astype(np.float64)
            R = d * fwd[ev]
            stats = {}
            for p in PERIODS:
                w = (period[ev] == p).astype(np.float64)
                N = E.T @ (E * w[:, None])
                S1 = [E.T @ (E * (w * R[:, j])[:, None]) for j in range(len(HORIZONS))]
                S2 = [E.T @ (E * (w * R[:, j] ** 2)[:, None]) for j in range(len(HORIZONS))]
                stats[p] = (N, S1, S2)
            for a, b in pairs:
                n_d = stats["descubrimiento"][0][a, b]
                if n_d < 50:
                    continue
                fa = fnames[a] if a != len(fnames) - 1 else "(ninguna)"
                fb = fnames[b] if b != len(fnames) - 1 else ""
                for j, h in enumerate(HORIZONS):
                    row = dict(inst=inst, tf=tf, trigger=tname, side=side, f1=fa, f2=fb, h=h)
                    for p, tag in zip(PERIODS, ("d", "v")):
                        N, S1, S2 = stats[p]
                        n = N[a, b]
                        mean = S1[j][a, b] / n if n > 0 else np.nan
                        var = S2[j][a, b] / n - mean ** 2 if n > 1 else np.nan
                        sd = np.sqrt(max(var, 1e-12)) if n > 1 else np.nan
                        row[f"n_{tag}"] = int(n)
                        row[f"gross_{tag}"] = mean
                        row[f"net_{tag}"] = mean - cost
                        row[f"t_{tag}"] = (mean - cost) / sd * np.sqrt(n) if n > 1 else np.nan
                    rows.append(row)
    return rows


def main():
    os.makedirs(OUT, exist_ok=True)
    all_rows = []
    for inst in INSTRUMENTS:
        for tf in TF_MIN:
            t0 = time.time()
            rows = scan_one(inst, tf)
            all_rows += rows
            print(f"{inst} {tf}: {len(rows):,} filas en {time.time() - t0:.0f}s", flush=True)
    res = pd.DataFrame(all_rows)
    res.to_csv(os.path.join(OUT, "scan.csv.gz"), index=False)

    key = ["tf", "trigger", "side", "f1", "f2", "h"]
    s1 = res[(res.n_d >= 300) & (res.net_d > 0) & (res.t_d >= 3)]
    s2 = s1[(s1.n_v >= 100) & (s1.net_v > 0) & (s1.t_v >= 2)]
    pos_v = res.assign(pos=res.net_v > 0).groupby(key).pos.sum().rename("mercados_pos_validacion")
    s3 = s2.join(pos_v, on=key)
    s3 = s3[s3.mercados_pos_validacion >= 2]
    s3.to_csv(os.path.join(OUT, "scan_survivors.csv"), index=False)
    print(f"combinaciones evaluadas: {len(res):,} | pasan descubrimiento: {len(s1):,} | "
          f"+ validación: {len(s2):,} | + 2 de 3 mercados: {len(s3):,}")


if __name__ == "__main__":
    main()
