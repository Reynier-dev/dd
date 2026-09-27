"""
Prueba aparte: momentum intradía (Gao, Han, Li y Zhou, 2018, Journal of Financial Economics).

Hipótesis publicada: el retorno de la primera media hora (cierre RTH anterior -> 10:00 ET)
predice el signo del retorno de la última media hora (15:30 -> 16:00 ET).

Regla: a las 15:30 entrar a mercado en la dirección del retorno de la primera media hora y
salir a mercado a las 16:00. Una operación por día, con los mismos costos del estudio
(comisión + 1 tick por lado). Variante: solo si |retorno de la primera media hora| supera su
mediana (días con movimiento temprano fuerte).

Salida: results/intraday_momentum.csv (por mercado y período)
"""
import os

import numpy as np
import pandas as pd

from features import COST_MARKET, INSTRUMENTS, POINT_VALUE, load, period_of

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")


def daily_legs(inst):
    m = load(inst, "1m")
    t = m.index
    minutes = t.hour * 60 + t.minute
    date = t.normalize().tz_localize(None)
    df = pd.DataFrame({"date": date, "min": minutes, "open": m["open"].values, "close": m["close"].values})
    rth = df[(df["min"] >= 570) & (df["min"] < 960)]
    g = rth.groupby("date")
    close_1600 = g["close"].last()
    first = rth[rth["min"] < 600].groupby("date")["close"].last()      # último cierre antes de las 10:00
    entry = rth[rth["min"] == 930].groupby("date")["open"].first()      # apertura de la vela de 15:30
    out = pd.DataFrame({"prev_close": close_1600.shift(1), "p1000": first, "entry": entry, "exit": close_1600}).dropna()
    out["r1"] = out["p1000"] / out["prev_close"] - 1
    out["period"] = period_of(pd.DatetimeIndex(out.index))
    return out


def main():
    rows = []
    for inst in INSTRUMENTS:
        d = daily_legs(inst)
        cost = COST_MARKET[inst]
        d["dir"] = np.sign(d["r1"])
        d["gross"] = d["dir"] * (d["exit"] - d["entry"])
        med = d.loc[d["period"] == "descubrimiento", "r1"].abs().median()
        for variant, mask in (("todos los días", np.ones(len(d), bool)),
                              ("primera media hora fuerte", d["r1"].abs() > med)):
            for p in ("descubrimiento", "validacion"):
                x = d[mask & (d["period"] == p)]
                net = x["gross"] - cost
                rows.append(dict(inst=inst, variant=variant, period=p, days=len(x),
                                 hit=(x["gross"] > 0).mean() * 100, gross_pts=x["gross"].mean(),
                                 net_pts=net.mean(), t_net=net.mean() / net.std(ddof=1) * np.sqrt(len(net)),
                                 net_usd_year=net.mean() * POINT_VALUE[inst] * 252 * len(x) / max(len(d[d["period"] == p]), 1)))
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(OUT, "intraday_momentum.csv"), index=False)
    print(res.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
