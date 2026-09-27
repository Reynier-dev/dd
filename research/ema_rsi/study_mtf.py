"""
Parte C — Alineación multi-timeframe (el "semáforo").

Para cada barra de 15m en RTH se calcula el régimen EMA (Alcista=+1, Neutral=0,
Bajista=-1) del propio 15m, de la última barra de 1h YA CERRADA y de la sesión
diaria ANTERIOR (sin mirar el futuro). La suma va de -3 (todo bajista) a +3 (todo
alcista). Se mide:
  1. El retorno futuro (en ATRs de 15m) a 8 barras (2h) y hasta el cierre de sesión.
  2. Los setups intradía de la Parte B con y sin el filtro "solo a favor del semáforo".

Salida: results/mtf_forward.csv, results/mtf_setups.csv
"""
import os

import numpy as np
import pandas as pd

from lib import COST_PTS, NAMES, add_indicators, load, metrics, session_masks, simulate, years_span
from study_setups import in_sample, setups

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
REG = {"Alcista": 1, "Neutral": 0, "Bajista": -1}
RSI_BINS = [0, 30, 40, 50, 60, 70, 100]


def attach_htf(df15, inst, bar_minutes=15):
    """Agrega regime_1h, rsi_1h y regime_1d usando solo barras superiores ya cerradas."""
    h1 = add_indicators(load(inst, "1h"))
    # .values: se RE-ETIQUETA cada barra con su hora de cierre. Pasar la Series tal cual haría que
    # pandas la realineara por etiqueta y se usaría la hora que todavía se está formando.
    h1 = pd.DataFrame({"regime_1h": h1["regime"].map(REG).values, "rsi14_1h": h1["rsi14"].values},
                      index=h1.index + pd.Timedelta(hours=1))
    end15 = pd.Series(df15.index + pd.Timedelta(minutes=bar_minutes), index=df15.index, name="end")
    m = pd.merge_asof(end15.to_frame(), h1, left_on="end", right_index=True, direction="backward")
    df15 = df15.assign(regime_1h=m["regime_1h"].values, rsi14_1h=m["rsi14_1h"].values)

    d1 = add_indicators(load(inst, "1d"))
    prev = d1[["regime", "rsi14", "rsi2"]].shift(1)  # sesión anterior, ya cerrada
    session = (df15.index + pd.Timedelta(hours=6)).normalize().tz_localize(None)
    df15["regime_1d"] = prev["regime"].map(REG).reindex(session).values
    df15["rsi2_1d"] = prev["rsi2"].reindex(session).values
    df15["regime_15m"] = df15["regime"].map(REG)
    df15["align"] = df15["regime_15m"] + df15["regime_1h"] + df15["regime_1d"]
    return df15


def forward(df, h):
    t = df.index
    minutes = t.hour * 60 + t.minute
    rth = pd.Series((minutes >= 570) & (minutes < 960), index=t)
    day = pd.Series(t.normalize(), index=t)
    fwd = (df["close"].shift(-h) - df["close"]) / df["atr"]
    ok = rth & rth.shift(-h, fill_value=False) & (day == day.shift(-h))
    # Hasta el cierre de la sesión regular: último close RTH del día
    last_close = df["close"].where(rth).groupby(day).transform("last")
    to_close = ((last_close - df["close"]) / df["atr"]).where(rth)
    return fwd.where(ok), to_close


def main():
    os.makedirs(OUT, exist_ok=True)
    fwd_rows, set_rows = [], []
    for inst in NAMES:
        df = attach_htf(add_indicators(load(inst, "15m")), inst)
        df["f8"], df["fclose"] = forward(df, 8)
        base = df.dropna(subset=["f8", "align"])
        drift8, driftc = base["f8"].mean(), base["fclose"].mean()
        for a, g in base.groupby("align"):
            fwd_rows.append(dict(inst=inst, align=int(a), n=len(g), f8=g["f8"].mean() - drift8,
                                 f8_up=(g["f8"] > 0).mean() * 100, fclose=g["fclose"].mean() - driftc,
                                 fclose_up=(g["fclose"] > 0).mean() * 100,
                                 t8=(g["f8"].mean() - drift8) / (g["f8"].std() / np.sqrt(len(g)))))
        # RSI de 15m dentro de semáforo totalmente alcista / bajista
        for a in (3, -3):
            g = base[base["align"] == a]
            for b, gg in g.groupby(pd.cut(g["rsi14"], RSI_BINS), observed=True):
                fwd_rows.append(dict(inst=inst, align=a, rsi_bin=str(b), n=len(gg), f8=gg["f8"].mean() - drift8,
                                     f8_up=(gg["f8"] > 0).mean() * 100, fclose=gg["fclose"].mean() - driftc,
                                     fclose_up=(gg["fclose"] > 0).mean() * 100,
                                     t8=(gg["f8"].mean() - drift8) / (gg["f8"].std() / np.sqrt(len(gg)))))

        allow, force = session_masks(df, "15m")
        cost = COST_PTS[inst]
        yrs = years_span(df.index)
        long_ok = (df["regime_1h"] == 1) & (df["regime_1d"] == 1)
        short_ok = (df["regime_1h"] == -1) & (df["regime_1d"] == -1)
        for name, (el, xl, es, xs) in setups(df).items():
            for side, ent, ex, d, ok in (("Largo", el, xl, 1, long_ok), ("Corto", es, xs, -1, short_ok)):
                for filt in ("sin filtro", "con semáforo 1h+1d"):
                    e = ent.fillna(False).values & allow
                    if filt != "sin filtro":
                        e &= ok.values
                    tr = simulate(df, e, ex.fillna(False).values, force, d, 2.0, 0.0, 1000, cost)
                    row = dict(inst=inst, setup=name, side=side, filter=filt)
                    row.update(metrics(tr, yrs))
                    ism = in_sample(tr["entry_time"])
                    row["IS_avgR"] = tr["R"][ism].mean()
                    row["OOS_avgR"] = tr["R"][~ism].mean()
                    set_rows.append(row)
        print(inst, "ok")
    pd.DataFrame(fwd_rows).to_csv(os.path.join(OUT, "mtf_forward.csv"), index=False)
    pd.DataFrame(set_rows).to_csv(os.path.join(OUT, "mtf_setups.csv"), index=False)


if __name__ == "__main__":
    main()
