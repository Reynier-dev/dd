"""
Fase 4 — Scalping a favor del swing diario validado.

Idea: el estudio de EMAs/RSI (research/ema_rsi) encontró UNA ventaja robusta, en diario: comprar
cuando el RSI(2) cierra < 10 con el cierre sobre la EMA 200, y salir al primer cierre sobre la
EMA 5. Esta fase prueba si hacer scalping SOLO EN LARGO y SOLO en los días en que ese swing está
abierto convierte los gatillos intradía en rentables. Es una confirmación de otra naturaleza:
otro timeframe con otra lógica, conocida antes de la apertura.

Estado diario (conocido a las 09:30, sin mirar el futuro): el swing está "activo" si la señal se
dio en un cierre anterior, ya se entró en una apertura anterior o de hoy, y ni el cierre de ayer
superó la EMA 5, ni se tocó el stop en días anteriores, ni pasaron 20 sesiones.

Pruebas (solo largos, NQ/ES/RTY, descubrimiento 2008-2013 y validación 2014-2016):
  A. Base: comprar en la apertura de las 09:30 y vender al cierre de las 16:00 de cada día activo.
  B. Los 27 gatillos intradía (1m/3m/5m) filtrados a días activos, con 3 salidas
     (stop 1,5 / objetivo 3 ATR; stop 2 / objetivo 3 ATR; stop 2 ATR y cierre de sesión) y
     ejecución a mercado o límite.

Reglas de selección (fijadas antes de correr):
  1. Descubrimiento: >= 100 operaciones, neto > 0, t agrupado por día >= 2,5.
  2. Validación: >= 40 operaciones, neto > 0, t agrupado >= 1,5.
  3. Neto > 0 en validación en al menos 2 de los 3 índices con la misma regla.
  4. Tiene que superar, en puntos por día activo, a la base A del mismo mercado y período.

Salida: results/phase4_base.csv, results/phase4.csv, results/phase4_survivors.csv
"""
import os
import sys

import numpy as np
import pandas as pd

from features import COST_MARKET, INSTRUMENTS, TF_MIN, cached_features, load, period_of
from phase2 import clustered
from signals import triggers
from sim import Minute, simulate

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
sys.path.insert(0, os.path.join(HERE, "..", "ema_rsi"))
from lib import add_indicators  # noqa: E402
from lib import load as load_daily  # noqa: E402

EXITS = (("stop 1,5 / obj 3 ATR", 1.5, 3.0, 24), ("stop 2 / obj 3 ATR", 2.0, 3.0, 24),
         ("stop 2 ATR, cierre de sesión", 2.0, 100.0, 1000))
EXECS = (("mercado", 0, 0.0), ("límite", 1, 0.0))


def swing_active_days(inst, entry_level=10.0, stop_mult=2.0, max_bars=20):
    """Días (fecha de sesión) en los que el swing RSI(2) diario está abierto a la apertura.
    Misma lógica que NinjaTrader/Indicators/EmaRsiSwing.cs."""
    d = add_indicators(load_daily(inst, "1d"))
    o, lo, c = d["open"].values, d["low"].values, d["close"].values
    e200, e5, r2, a = d["ema200"].values, d["ema5"].values, d["rsi2"].values, d["atr"].values
    active, entry_day = set(), set()
    state, sb, sig_atr = 0, -1, np.nan
    stop = np.nan
    for i in range(len(d)):
        if state == 1:
            state, stop = 2, o[i] - stop_mult * sig_atr
            entry_day.add(d.index[i])
        if state == 2:
            active.add(d.index[i])  # abierto a la apertura de hoy
            if lo[i] <= stop or i - sb >= max_bars:
                state = 0
            elif c[i] > e5[i]:
                state = 0
                continue  # la salida es en la apertura de mañana; hoy no hay señal nueva
        if state == 0 and c[i] > e200[i] and r2[i] < entry_level:
            state, sb, sig_atr = 1, i, a[i]
    return active, entry_day


def base_day_trades(inst, days):
    m = load(inst, "1m")
    t = m.index
    minutes = t.hour * 60 + t.minute
    date = t.normalize().tz_localize(None)
    df = pd.DataFrame({"date": date, "min": minutes, "open": m["open"].values, "close": m["close"].values})
    rth = df[(df["min"] >= 570) & (df["min"] < 960)]
    g = rth.groupby("date")
    day = pd.DataFrame({"open": g["open"].first(), "close": g["close"].last()})
    day["pts"] = day["close"] - day["open"] - COST_MARKET[inst]
    day["active"] = day.index.isin(list(days))
    day["period"] = period_of(pd.DatetimeIndex(day.index))
    return day


def main():
    os.makedirs(OUT, exist_ok=True)
    base_rows, rows = [], []
    for inst in INSTRUMENTS:
        active, entry_day = swing_active_days(inst)
        day = base_day_trades(inst, active)
        for p in ("descubrimiento", "validacion"):
            for label, mask in (("días de swing activo", day["active"]), ("todos los días", np.ones(len(day), bool))):
                x = day[mask & (day["period"] == p)]["pts"]
                base_rows.append(dict(inst=inst, period=p, días=label, n=len(x), net_pts=x.mean(),
                                      t=x.mean() / x.std(ddof=1) * np.sqrt(len(x)), win=(x > 0).mean() * 100))
        minute = Minute(inst)
        for tf in TF_MIN:
            f = cached_features(inst, tf)
            on = pd.Series(f["date"].values).isin(list(active)).to_numpy()
            trig = triggers(f)
            period = f["period"].astype(str).to_numpy()
            ok = f["signal_ok"].to_numpy(bool) & on
            for tname, (tl, _) in trig.items():
                for p in ("descubrimiento", "validacion"):
                    sig = np.flatnonzero(tl & ok & (period == p))
                    if len(sig) < 10:
                        continue
                    for ex_name, sm, tm, mb in EXITS:
                        for exe, mode, off in EXECS:
                            tr = simulate(minute, f, tf, sig, 1, sm, tm, mb, mode=mode, offset=off)
                            mean, tcl = clustered(tr, tr["entry_time"].dt.normalize().to_numpy())
                            days_n = tr["entry_time"].dt.normalize().nunique()
                            rows.append(dict(inst=inst, tf=tf, trigger=tname, exit=ex_name, exec=exe, period=p,
                                             n=len(tr), days=days_n, net_pts=mean, t_clu=tcl,
                                             pts_per_day=tr["pts"].sum() / max(days_n, 1),
                                             win=(tr["pts"] > 0).mean() * 100 if len(tr) else np.nan))
            print(inst, tf, flush=True)
    base = pd.DataFrame(base_rows)
    base.to_csv(os.path.join(OUT, "phase4_base.csv"), index=False)
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(OUT, "phase4.csv"), index=False)

    key = ["inst", "tf", "trigger", "exit", "exec"]
    j = res[res.period == "descubrimiento"].set_index(key).join(
        res[res.period == "validacion"].set_index(key), lsuffix="_d", rsuffix="_v", how="inner").reset_index()
    b = base[base["días"] == "días de swing activo"].pivot(index="inst", columns="period", values="net_pts")
    j["base_d"] = j["inst"].map(b["descubrimiento"])
    j["base_v"] = j["inst"].map(b["validacion"])
    s1 = j[(j.n_d >= 100) & (j.net_pts_d > 0) & (j.t_clu_d >= 2.5)]
    s2 = s1[(s1.n_v >= 40) & (s1.net_pts_v > 0) & (s1.t_clu_v >= 1.5)]
    rule = ["tf", "trigger", "exit", "exec"]
    pos = j.assign(pos=j.net_pts_v > 0).groupby(rule).pos.sum().rename("mercados_pos_validacion")
    s3 = s2.join(pos, on=rule)
    s3 = s3[s3.mercados_pos_validacion >= 2]
    s4 = s3[(s3.pts_per_day_d > s3.base_d) & (s3.pts_per_day_v > s3.base_v)]
    j.to_csv(os.path.join(OUT, "phase4_joined.csv"), index=False)
    s4.to_csv(os.path.join(OUT, "phase4_survivors.csv"), index=False)
    print(base.round(3).to_string(index=False))
    print(f"simulaciones: {len(j):,} | desc: {len(s1)} | + valid: {len(s2)} | + 2 de 3: {len(s3)} | + supera la base: {len(s4)}")


if __name__ == "__main__":
    main()
