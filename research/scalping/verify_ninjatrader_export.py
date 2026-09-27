"""
Verifica el mejor candidato de scalping del estudio con TUS datos recientes de NinjaTrader 8.

Candidato (research/scalping/REPORT.md, Fase 5): en velas de 1 minuto, comprar el retroceso a la
EMA 9 cuando las EMAs 9 > 21 > 50 están alineadas al alza (el mínimo toca la EMA 9 y la vela
cierra por encima), solo en días con gap alcista (apertura RTH sobre el cierre RTH anterior).
Entrada a mercado en la apertura de la vela siguiente, salida a mercado 24 minutos después o a
las 16:00 ET. Una operación a la vez. En 2008-2020 tuvo ventaja BRUTA estable en NQ y ES
(0,12-0,20 ATR por operación), pero el costo fue mayor. Este script mide si con tus precios y
costos actuales la ventaja neta es positiva.

Cómo exportar desde NinjaTrader 8:
  Tools -> Historical Data -> pestaña Export -> instrumento (p. ej. NQ 12-26), tipo "Last",
  intervalo "Minute", rango de fechas (idealmente 2 años o más) -> Export. Genera un .txt con
  líneas "yyyyMMdd HHmmss;open;high;low;close;volume" (la hora es la de CIERRE de la vela).

Uso:
  python verify_ninjatrader_export.py "NQ 12-26.Last.txt"
  python verify_ninjatrader_export.py archivo.txt --tick 0.25 --point-value 20 --commission 4.50 --slippage-ticks 1
  python verify_ninjatrader_export.py archivo.txt --tz UTC      # si la exportación está en UTC

Solo necesita pandas y numpy.
"""
import argparse
import sys

import numpy as np
import pandas as pd

RTH_OPEN, RTH_CLOSE = 570, 960
FIRST_SIGNAL, LAST_SIGNAL = 575, 940
HOLD = 24


def load_export(path, tz, stamp):
    df = pd.read_csv(path, sep=";", header=None, names=["ts", "open", "high", "low", "close", "volume"])
    t = pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S")
    if stamp == "end":  # NinjaTrader marca la vela con su hora de cierre; el estudio usa la de inicio
        t = t - pd.Timedelta(minutes=1)
    t = t.dt.tz_localize(tz).dt.tz_convert("America/New_York") if tz != "America/New_York" \
        else t.dt.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")
    df.index = pd.DatetimeIndex(t)
    df = df[df.index.notna()].drop(columns="ts").astype(float)
    return df[~df.index.duplicated()].sort_index()


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def run(df, cost_pts, point_value):
    t = df.index
    minutes = np.asarray(t.hour * 60 + t.minute)
    date = np.asarray(t.normalize().tz_localize(None))
    rth = (minutes >= RTH_OPEN) & (minutes < RTH_CLOSE)
    c, o, lo = df["close"].to_numpy(), df["open"].to_numpy(), df["low"].to_numpy()
    e9, e21, e50 = (ema(df["close"], n).to_numpy() for n in (9, 21, 50))
    a = atr(df).to_numpy()

    r = pd.DataFrame({"date": date[rth], "open": o[rth], "close": c[rth]})
    day = r.groupby("date").agg(day_open=("open", "first"), day_close=("close", "last"))
    day["prev_close"] = day["day_close"].shift(1)
    gap_up = (day["day_open"] > day["prev_close"]).reindex(date).fillna(False).to_numpy()

    pos = np.arange(len(df))
    last = pd.Series(np.where(rth, pos, -1)).groupby(date).transform("max").to_numpy()
    signal_ok = rth & (minutes >= FIRST_SIGNAL) & (minutes <= LAST_SIGNAL) & (pos < last)
    trigger = (e9 > e21) & (e21 > e50) & (lo <= e9) & (c > e9)

    rows, nxt = [], -1
    for kind, mask in (("setup", trigger & gap_up & signal_ok), ("control", gap_up & signal_ok)):
        nxt = -1
        for i in np.flatnonzero(mask):
            if i < nxt or i + 1 >= len(df):
                continue
            x = min(i + HOLD, last[i])
            gross = c[x] - o[i + 1]
            rows.append(dict(kind=kind, time=t[i], year=t[i].year, day=date[i], gross_pts=gross,
                             net_pts=gross - cost_pts, gross_atr=gross / a[i], cost_atr=cost_pts / a[i]))
            nxt = x
    return pd.DataFrame(rows)


def summary(x, point_value):
    net = x["net_pts"].to_numpy()
    s = pd.Series(net).groupby(x["day"].to_numpy()).agg(["sum", "count"])
    mu = net.mean()
    var = ((s["sum"] - s["count"] * mu) ** 2).sum() / len(net) ** 2
    return pd.Series({"operaciones": len(x), "bruto_pts": x["gross_pts"].mean(), "neto_pts": mu,
                      "neto_usd": mu * point_value, "aciertos_%": (net > 0).mean() * 100,
                      "t_por_dia": mu / np.sqrt(var) if var > 0 else np.nan,
                      "bruto_ATR": x["gross_atr"].mean(), "costo_ATR": x["cost_atr"].mean()})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archivo")
    ap.add_argument("--tick", type=float, default=0.25)
    ap.add_argument("--point-value", type=float, default=20.0, help="USD por punto (NQ 20, ES 50, MNQ 2, MES 5)")
    ap.add_argument("--commission", type=float, default=4.50, help="USD ida y vuelta por contrato")
    ap.add_argument("--slippage-ticks", type=float, default=1.0, help="ticks de deslizamiento POR LADO")
    ap.add_argument("--tz", default="America/New_York", help="zona horaria de la exportación")
    ap.add_argument("--stamp", choices=["end", "start"], default="end", help="la hora marca el cierre (NinjaTrader) o el inicio de la vela")
    args = ap.parse_args(argv)

    df = load_export(args.archivo, args.tz, args.stamp)
    cost = args.commission / args.point_value + 2 * args.slippage_ticks * args.tick
    res = run(df, cost, args.point_value)
    if res.empty:
        sys.exit("No se encontraron señales. ¿La exportación es de velas de 1 minuto y cubre el horario regular?")
    pd.set_option("display.width", 160)
    print(f"Datos: {df.index[0]} -> {df.index[-1]}  ({len(df):,} velas)")
    print(f"Costo por operación: {cost:.3f} puntos = USD {cost * args.point_value:.2f}\n")
    out = res.groupby("kind").apply(lambda g: summary(g, args.point_value), include_groups=False)
    print(out.rename(index={"setup": "Retroceso EMA 9 + gap alcista", "control": "Control: cualquier minuto, días de gap"}).round(3).to_string())
    print("\nPor año (setup):")
    print(res[res["kind"] == "setup"].groupby("year").apply(lambda g: summary(g, args.point_value), include_groups=False)
          [["operaciones", "neto_pts", "neto_usd", "t_por_dia", "bruto_ATR", "costo_ATR"]].round(3).to_string())
    print("\nLectura: la regla vale la pena solo si el neto es positivo con t_por_dia >= 2 y le gana al control.")


if __name__ == "__main__":
    main()
