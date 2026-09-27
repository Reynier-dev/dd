"""
Construye barras OHLCV de 5m / 15m / 1h / diario a partir de los CSV de 1 minuto
de Oanda publicados en github.com/FutureSharks/financial-data (2005-2020).

Los CSV vienen en UTC. Todo se convierte a America/New_York para que las sesiones
coincidan con las de los futuros de CME (ES/NQ): la "sesión" diaria arranca a las
18:00 ET y cierra a las 17:00 ET del día siguiente.

Uso:
    python fetch_data.py                   # descarga los CSV de 1 minuto a data/raw
    python build_bars.py                   # genera data/bars/<INSTRUMENTO>_<tf>.pkl
"""
import glob
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.environ.get("EMA_RSI_RAW", os.path.join(HERE, "data", "raw"))
OUT_DIR = os.path.join(HERE, "data", "bars")

INSTRUMENTS = ["NAS100_USD", "SPX500_USD", "US2000_USD", "XAU_USD", "EUR_USD", "WTICO_USD"]
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def load_minutes(instrument):
    files = sorted(glob.glob(os.path.join(RAW_DIR, f"oanda-{instrument}-*.csv")))
    if not files:
        raise FileNotFoundError(f"No hay CSV para {instrument} en {RAW_DIR}")
    df = pd.concat((pd.read_csv(f) for f in files), ignore_index=True)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert("America/New_York")
    df = df.drop_duplicates("time").set_index("time").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    # Descarta velas imposibles (high < low, precios <= 0)
    df = df[(df["high"] >= df["low"]) & (df["low"] > 0)]
    return df


def resample_intraday(m1, rule):
    bars = m1.resample(rule, label="left", closed="left").agg(AGG)
    return bars.dropna(subset=["open"])


def resample_daily(m1):
    # Sesión estilo CME: 18:00 ET (día D-1) -> 17:00 ET (día D). Desplazando +6h,
    # las 18:00 ET caen en las 00:00 del día D y un groupby por fecha agrupa la sesión.
    session = (m1.index + pd.Timedelta(hours=6)).normalize().tz_localize(None)
    daily = m1.groupby(session).agg(AGG)
    daily.index.name = "session"
    daily = daily[daily.index.dayofweek < 5]  # algunos feeds dejan velas sueltas en fin de semana
    return daily


def main(instruments):
    os.makedirs(OUT_DIR, exist_ok=True)
    for inst in instruments:
        m1 = load_minutes(inst)
        print(f"{inst}: {len(m1):,} velas de 1m  {m1.index[0]} -> {m1.index[-1]}")
        for tf, rule in [("5m", "5min"), ("15m", "15min"), ("1h", "1h")]:
            bars = resample_intraday(m1, rule)
            bars.to_pickle(os.path.join(OUT_DIR, f"{inst}_{tf}.pkl"))
            print(f"   {tf}: {len(bars):,} barras")
        daily = resample_daily(m1)
        daily.to_pickle(os.path.join(OUT_DIR, f"{inst}_1d.pkl"))
        print(f"   1d: {len(daily):,} barras")


if __name__ == "__main__":
    main(sys.argv[1:] or INSTRUMENTS)
