"""
¿Dónde se gana el swing diario RSI(2)? Descompone cada día con el swing abierto en
  - tramo nocturno: cierre RTH anterior (16:00) -> apertura RTH (09:30)
  - tramo intradía: apertura RTH (09:30) -> cierre RTH (16:00)
comparado con todos los días. En puntos, sin costos (es una descomposición, no una estrategia).

Salida: results/swing_decomposition.csv
"""
import os

import numpy as np
import pandas as pd

from features import INSTRUMENTS, load, period_of
from phase4_swing_context import swing_active_days

HERE = os.path.dirname(os.path.abspath(__file__))


def legs(inst):
    m = load(inst, "1m")
    t = m.index
    minutes = t.hour * 60 + t.minute
    date = t.normalize().tz_localize(None)
    df = pd.DataFrame({"date": date, "min": minutes, "open": m["open"].values, "close": m["close"].values})
    rth = df[(df["min"] >= 570) & (df["min"] < 960)]
    g = rth.groupby("date")
    d = pd.DataFrame({"open": g["open"].first(), "close": g["close"].last()})
    d["noche"] = d["open"] - d["close"].shift(1)
    d["intradia"] = d["close"] - d["open"]
    d["noche_pct"] = d["noche"] / d["close"].shift(1) * 100
    d["intradia_pct"] = d["intradia"] / d["open"] * 100
    d["period"] = period_of(pd.DatetimeIndex(d.index))
    return d.dropna()


def main():
    rows = []
    for inst in INSTRUMENTS:
        active, _ = swing_active_days(inst)
        d = legs(inst)
        d["activo"] = d.index.isin(list(active))
        for p in ("descubrimiento", "validacion", "todo 2008-2016"):
            base = d if p == "todo 2008-2016" else d[d["period"] == p]
            base = base[base["period"].isin(["descubrimiento", "validacion"])]
            for label, x in (("swing activo", base[base["activo"]]), ("todos los días", base)):
                row = dict(inst=inst, period=p, días=label, n=len(x))
                for leg in ("noche", "intradia"):
                    v = x[f"{leg}_pct"]
                    row[f"{leg}_pct"] = v.mean()
                    row[f"{leg}_t"] = v.mean() / v.std(ddof=1) * np.sqrt(len(v))
                rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(HERE, "results", "swing_decomposition.csv"), index=False)
    print(out.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
