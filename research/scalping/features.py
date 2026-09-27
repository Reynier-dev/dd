"""
Indicadores, niveles y contexto para el estudio de scalping (1m / 3m / 5m).

Reglas para no mirar el futuro:
  - Todo se calcula con información disponible al CIERRE de la vela.
  - Las velas de 15m / 1h solo aportan barras YA CERRADAS (se re-etiquetan con su hora de
    cierre usando .values; ver research/ema_rsi/REPORT.md, sección 6).
  - Máximo/mínimo del día anterior, de la noche y del rango de apertura solo existen
    después de que ese período terminó.
"""
import os
import sys

import numpy as np
import pandas as pd
from numba import njit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ema_rsi"))
from lib import atr, ema, rsi  # noqa: E402

BARS = os.path.join(HERE, "data", "bars")
HTF_BARS = os.path.join(HERE, "..", "ema_rsi", "data", "bars")
FEAT = os.path.join(HERE, "data", "features")

INSTRUMENTS = ["NAS100_USD", "SPX500_USD", "US2000_USD"]
SHORT = {"NAS100_USD": "NQ", "SPX500_USD": "ES", "US2000_USD": "RTY"}
PARTNER = {"NAS100_USD": "SPX500_USD", "SPX500_USD": "NAS100_USD", "US2000_USD": "SPX500_USD"}
TF_MIN = {"1m": 1, "3m": 3, "5m": 5}

# Futuros CME: tamaño de tick y comisión ida y vuelta (USD 4,50 por contrato) en puntos.
TICK = {"NAS100_USD": 0.25, "SPX500_USD": 0.25, "US2000_USD": 0.10}
POINT_VALUE = {"NAS100_USD": 20.0, "SPX500_USD": 50.0, "US2000_USD": 50.0}
COMMISSION = {k: 4.50 / v for k, v in POINT_VALUE.items()}
# Orden a mercado: comisión + 1 tick de deslizamiento por lado.
COST_MARKET = {k: COMMISSION[k] + 2 * TICK[k] for k in TICK}

PERIODS = {"descubrimiento": ("2008-01-01", "2013-12-31"),
           "validacion": ("2014-01-01", "2016-12-31"),
           "reserva": ("2017-01-01", "2020-12-31")}

RTH_OPEN, RTH_CLOSE = 570, 960        # 09:30 y 16:00 ET, en minutos
SIGNAL_FIRST, SIGNAL_LAST = 575, 940  # velas de señal entre 09:35 y 15:40 (inicio de vela)


def period_of(index):
    t = index.tz_localize(None) if index.tz is not None else index
    out = np.full(len(t), "", dtype=object)
    for name, (a, b) in PERIODS.items():
        out[(t >= pd.Timestamp(a)) & (t < pd.Timestamp(b) + pd.Timedelta(days=1))] = name
    return out


# ----------------------------------------------------------------------------- numba helpers
@njit(cache=True)
def _rolling_mad(x, w):
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(w - 1, n):
        s = 0.0
        for j in range(i - w + 1, i + 1):
            s += x[j]
        m = s / w
        d = 0.0
        for j in range(i - w + 1, i + 1):
            d += abs(x[j] - m)
        out[i] = d / w
    return out


@njit(cache=True)
def _supertrend(h, l, c, a, mult):
    n = len(c)
    direction = np.zeros(n)
    upper = np.zeros(n)
    lower = np.zeros(n)
    for i in range(n):
        mid = (h[i] + l[i]) / 2.0
        bu = mid + mult * a[i]
        bl = mid - mult * a[i]
        if i == 0 or np.isnan(a[i]):
            upper[i], lower[i], direction[i] = bu, bl, 1.0
            continue
        upper[i] = bu if (bu < upper[i - 1] or c[i - 1] > upper[i - 1]) else upper[i - 1]
        lower[i] = bl if (bl > lower[i - 1] or c[i - 1] < lower[i - 1]) else lower[i - 1]
        if direction[i - 1] == 1.0:
            direction[i] = -1.0 if c[i] < lower[i] else 1.0
        else:
            direction[i] = 1.0 if c[i] > upper[i] else -1.0
    return direction


@njit(cache=True)
def _swing_sweeps(h, l, c, strength):
    """Barridos de liquidez como en VwapLiquiditySweep.cs: el precio perfora el último swing
    confirmado (fractal de `strength` velas por lado) con la mecha y cierra de vuelta adentro.
    Un nivel barrido se invalida."""
    n = len(c)
    bull = np.zeros(n, np.bool_)
    bear = np.zeros(n, np.bool_)
    last_hi = np.nan
    last_lo = np.nan
    for i in range(2 * strength, n):
        p = i - strength
        is_hi = True
        is_lo = True
        for j in range(1, strength + 1):
            if h[p - j] > h[p] or h[p + j] > h[p]:
                is_hi = False
            if l[p - j] < l[p] or l[p + j] < l[p]:
                is_lo = False
        if is_hi:
            last_hi = h[p]
        if is_lo:
            last_lo = l[p]
        if not np.isnan(last_hi) and h[i] > last_hi and c[i] < last_hi:
            bear[i] = True
            last_hi = np.nan
        if not np.isnan(last_lo) and l[i] < last_lo and c[i] > last_lo:
            bull[i] = True
            last_lo = np.nan
    return bull, bear


# ----------------------------------------------------------------------------- building blocks
def load(inst, tf):
    return pd.read_pickle(os.path.join(BARS, f"{inst}_{tf}.pkl"))


def session_frame(df, tf):
    t = df.index
    minutes = np.asarray(t.hour * 60 + t.minute)
    date = np.asarray(t.normalize().tz_localize(None))
    rth = (minutes >= RTH_OPEN) & (minutes < RTH_CLOSE)
    s = pd.DataFrame({"minutes": minutes, "date": date, "rth": rth}, index=t)
    # índice de la última vela RTH de cada día (para cortar horizontes y forzar el cierre)
    pos = np.arange(len(df))
    last = pd.Series(np.where(rth, pos, -1), index=t).groupby(date).transform("max").values
    s["last_rth_pos"] = np.where(rth, last, -1)
    s["signal_ok"] = rth & (minutes >= SIGNAL_FIRST) & (minutes <= SIGNAL_LAST) & (pos < s["last_rth_pos"].values)
    return s


def rth_vwap(df, s):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    v = df["volume"].clip(lower=0) + 1.0  # +1: el volumen de Oanda es un conteo de ticks, a veces 0
    key = np.where(s["rth"], s["date"], np.datetime64("NaT"))
    g = pd.Series(key, index=df.index)
    pv = (tp * v).where(s["rth"]).groupby(g).cumsum()
    ppv = (tp * tp * v).where(s["rth"]).groupby(g).cumsum()
    vv = v.where(s["rth"]).groupby(g).cumsum()
    vwap = pv / vv
    sd = np.sqrt((ppv / vv - vwap ** 2).clip(lower=0))
    return vwap, sd


def daily_levels(df, s):
    """PDH/PDL/PDC del RTH anterior, apertura RTH del día, máximos/mínimos de la noche y del
    rango de apertura de 15 minutos. Todos mapeados solo cuando ya son conocidos."""
    rth = s["rth"].values
    d = pd.DataFrame({"date": s["date"].values, "high": df["high"].values, "low": df["low"].values,
                      "close": df["close"].values, "open": df["open"].values,
                      "minutes": s["minutes"].values})
    r = d[rth]
    day = r.groupby("date").agg(dh=("high", "max"), dl=("low", "min"), dc=("close", "last"), do=("open", "first"))
    prev = day[["dh", "dl", "dc"]].shift(1)
    out = pd.DataFrame(index=df.index)
    out["pdh"] = prev["dh"].reindex(d["date"]).values
    out["pdl"] = prev["dl"].reindex(d["date"]).values
    out["pdc"] = prev["dc"].reindex(d["date"]).values
    out["rth_open"] = day["do"].reindex(d["date"]).values
    # Noche: de 18:00 del día anterior a 09:30 (sesión = fecha de las 09:30)
    session = (df.index + pd.Timedelta(hours=6)).normalize().tz_localize(None)
    night = (d["minutes"].values < RTH_OPEN) | (d["minutes"].values >= 18 * 60)
    n = pd.DataFrame({"session": np.asarray(session), "high": d["high"], "low": d["low"]})[night]
    on = n.groupby("session").agg(onh=("high", "max"), onl=("low", "min"))
    out["onh"] = on["onh"].reindex(d["date"]).values
    out["onl"] = on["onl"].reindex(d["date"]).values
    # Rango de apertura: 09:30-09:45
    orr = d[rth & (d["minutes"].values < RTH_OPEN + 15)].groupby("date").agg(orh=("high", "max"), orl=("low", "min"))
    out["orh"] = orr["orh"].reindex(d["date"]).values
    out["orl"] = orr["orl"].reindex(d["date"]).values
    known = rth & (d["minutes"].values >= RTH_OPEN + 15)
    out.loc[~known, ["orh", "orl"]] = np.nan
    out.loc[~rth, ["pdh", "pdl", "pdc", "rth_open", "onh", "onl"]] = np.nan
    return out


def htf_regime(df, inst, tf_minutes, htf):
    """Régimen EMA 50/200 (+1/0/-1) de la última barra de 15m o 1h YA CERRADA."""
    h = pd.read_pickle(os.path.join(HTF_BARS, f"{inst}_{htf}.pkl"))
    c = h["close"]
    e50, e200 = ema(c, 50), ema(c, 200)
    reg = np.where((c > e200) & (e50 > e200), 1, np.where((c < e200) & (e50 < e200), -1, 0))
    step = pd.Timedelta(minutes=15) if htf == "15m" else pd.Timedelta(hours=1)
    closed = pd.DataFrame({"reg": reg.astype(float)}, index=h.index + step)
    end = pd.DataFrame({"end": df.index + pd.Timedelta(minutes=tf_minutes)})
    m = pd.merge_asof(end, closed, left_on="end", right_index=True, direction="backward")
    return m["reg"].values


def daily_regime(df, inst):
    d = pd.read_pickle(os.path.join(HTF_BARS, f"{inst}_1d.pkl"))
    c = d["close"]
    e50, e200 = ema(c, 50), ema(c, 200)
    reg = pd.Series(np.where((c > e200) & (e50 > e200), 1, np.where((c < e200) & (e50 < e200), -1, 0)),
                    index=d.index).shift(1)
    session = (df.index + pd.Timedelta(hours=6)).normalize().tz_localize(None)
    return reg.reindex(session).fillna(0).values


def add_features(inst, tf):
    df = load(inst, tf)
    s = session_frame(df, tf)
    o, h, l, c, v = (df[k] for k in ("open", "high", "low", "close", "volume"))
    f = pd.DataFrame(index=df.index)
    for k in ("open", "high", "low", "close", "volume"):
        f[k] = df[k]
    for k in s.columns:
        f[k] = s[k].values

    for n in (9, 20, 21, 50, 200):
        f[f"ema{n}"] = ema(c, n)
    f["rsi2"], f["rsi7"], f["rsi14"] = rsi(c, 2), rsi(c, 7), rsi(c, 14)
    f["atr"] = atr(df, 14)
    f["atr_med"] = f["atr"].rolling(500, min_periods=100).median()

    ma, sd = c.rolling(20).mean(), c.rolling(20).std()
    f["bb_up"], f["bb_lo"] = ma + 2 * sd, ma - 2 * sd
    bw = (f["bb_up"] - f["bb_lo"]) / ma
    f["bb_bw_pct"] = bw.rolling(100).rank(pct=True)
    f["kc_up"], f["kc_lo"] = f["ema20"] + 1.5 * f["atr"], f["ema20"] - 1.5 * f["atr"]

    ll, hh = l.rolling(14).min(), h.rolling(14).max()
    k = (100 * (c - ll) / (hh - ll).replace(0, np.nan)).rolling(3).mean()
    f["stoch_k"], f["stoch_d"] = k, k.rolling(3).mean()

    macd = ema(c, 12) - ema(c, 26)
    f["macd_hist"] = macd - ema(macd, 9)

    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr_s = f["atr"]
    pdi = 100 * pdm.ewm(alpha=1 / 14, adjust=False).mean() / tr_s
    ndi = 100 * ndm.ewm(alpha=1 / 14, adjust=False).mean() / tr_s
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    f["pdi"], f["ndi"], f["adx"] = pdi, ndi, dx.ewm(alpha=1 / 14, adjust=False).mean()

    tp = (h + l + c) / 3
    mad = _rolling_mad(tp.values, 20)
    f["cci"] = (tp - tp.rolling(20).mean()) / (0.015 * pd.Series(mad, index=df.index).replace(0, np.nan))

    f["don_hi"], f["don_lo"] = h.shift(1).rolling(20).max(), l.shift(1).rolling(20).min()
    f["st_dir"] = _supertrend(h.values, l.values, c.values, atr(df, 10).values, 3.0)
    f["relvol"] = v / v.rolling(20).mean().replace(0, np.nan)

    f["vwap"], f["vwap_sd"] = rth_vwap(df, s)
    lv = daily_levels(df, s)
    for col in lv.columns:
        f[col] = lv[col].values

    bull_sw, bear_sw = _swing_sweeps(h.values, l.values, c.values, 5)
    f["sweep_bull"], f["sweep_bear"] = bull_sw, bear_sw

    f["reg15"] = htf_regime(df, inst, TF_MIN[tf], "15m")
    f["reg1h"] = htf_regime(df, inst, TF_MIN[tf], "1h")
    f["reg1d"] = daily_regime(df, inst)

    # Mercado hermano (divergencia SMT y confirmación cruzada), alineado por hora de vela
    p = load(PARTNER[inst], tf).reindex(df.index)
    ps = session_frame(p.dropna(), tf).reindex(df.index)
    pv, _ = rth_vwap(p.dropna(), session_frame(p.dropna(), tf))
    f["x_close"] = p["close"]
    f["x_vwap"] = pv.reindex(df.index)
    f["x_low"], f["x_high"] = p["low"], p["high"]
    f["x_ll20"] = p["low"].shift(1).rolling(20, min_periods=20).min()
    f["x_hh20"] = p["high"].shift(1).rolling(20, min_periods=20).max()
    f["x_ok"] = ps["rth"].fillna(False).astype(bool).values & p["close"].notna().values

    f["period"] = pd.Categorical(period_of(df.index))
    floats = f.select_dtypes("float64").columns
    f[floats] = f[floats].astype("float32")
    return f


def cached_features(inst, tf):
    os.makedirs(FEAT, exist_ok=True)
    path = os.path.join(FEAT, f"{inst}_{tf}.pkl")
    if os.path.exists(path):
        return pd.read_pickle(path)
    f = add_features(inst, tf)
    f.to_pickle(path)
    return f


if __name__ == "__main__":
    for inst in INSTRUMENTS:
        for tf in TF_MIN:
            f = cached_features(inst, tf)
            print(inst, tf, f.shape)
