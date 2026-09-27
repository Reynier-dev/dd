"""
Barras de 1m, 3m y 5m (hora de Nueva York) para el estudio de scalping, a partir de los
CSV de 1 minuto de Oanda que descarga research/ema_rsi/fetch_data.py.

    python build_bars.py            # usa ../ema_rsi/data/raw (o la variable EMA_RSI_RAW)
"""
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ema_rsi"))
from build_bars import AGG, load_minutes  # noqa: E402

OUT_DIR = os.path.join(HERE, "data", "bars")
INSTRUMENTS = ["NAS100_USD", "SPX500_USD", "US2000_USD"]


def main(instruments):
    os.makedirs(OUT_DIR, exist_ok=True)
    for inst in instruments:
        m1 = load_minutes(inst)
        m1 = m1[m1.index >= "2007-06-01"]  # los años previos tienen muchos minutos sin cotización
        m1.to_pickle(os.path.join(OUT_DIR, f"{inst}_1m.pkl"))
        for tf, rule in (("3m", "3min"), ("5m", "5min")):
            bars = m1.resample(rule, label="left", closed="left").agg(AGG).dropna(subset=["open"])
            bars.to_pickle(os.path.join(OUT_DIR, f"{inst}_{tf}.pkl"))
        print(inst, f"{len(m1):,} velas de 1m")


if __name__ == "__main__":
    main(sys.argv[1:] or INSTRUMENTS)
