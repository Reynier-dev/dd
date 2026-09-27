"""
Descarga los CSV de 1 minuto (Oanda, 2005-2020) del repositorio público
github.com/FutureSharks/financial-data a data/raw/.

    python fetch_data.py                  # instrumentos por defecto
    python fetch_data.py NAS100_USD       # solo uno
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.environ.get("EMA_RSI_RAW", os.path.join(HERE, "data", "raw"))
BASE = ("https://raw.githubusercontent.com/FutureSharks/financial-data/master/"
        "pyfinancialdata/data/currencies/oanda")
INSTRUMENTS = ["NAS100_USD", "SPX500_USD", "US2000_USD", "XAU_USD", "EUR_USD", "WTICO_USD"]


def fetch(inst, year, month):
    name = f"oanda-{inst}-{year}-{month}.csv"
    dest = os.path.join(RAW_DIR, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return name, "ok (cache)"
    try:
        with urlopen(f"{BASE}/{inst}/{year}/{name}", timeout=120) as r:
            data = r.read()
    except Exception as e:  # algunos meses no existen (p.ej. XAU 2005)
        return name, f"saltado ({e})"
    with open(dest, "wb") as f:
        f.write(data)
    return name, "ok"


def main(instruments):
    os.makedirs(RAW_DIR, exist_ok=True)
    jobs = [(i, y, m) for i in instruments for y in range(2005, 2021) for m in range(1, 13)]
    with ThreadPoolExecutor(16) as ex:
        for name, status in ex.map(lambda a: fetch(*a), jobs):
            if status != "ok (cache)":
                print(name, status)


if __name__ == "__main__":
    main(sys.argv[1:] or INSTRUMENTS)
