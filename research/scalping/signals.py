"""
Gatillos (eventos de entrada) y confirmaciones (filtros) del estudio de scalping.

Cada función devuelve arrays booleanos (largo, corto), evaluados al cierre de la vela.
Los cortos son el espejo exacto de los largos.
"""
import numpy as np


def _prev(x):
    out = np.empty_like(x)
    out[0] = np.nan
    out[1:] = x[:-1]
    return out


def _a(f, k):
    return f[k].to_numpy(dtype=np.float64)


def triggers(f):
    o, h, l, c = (_a(f, k) for k in ("open", "high", "low", "close"))
    po, ph, pl, pc = _prev(o), _prev(h), _prev(l), _prev(c)
    e9, e21, e50 = _a(f, "ema9"), _a(f, "ema21"), _a(f, "ema50")
    vw, sd = _a(f, "vwap"), _a(f, "vwap_sd")
    pvw = _prev(vw)
    a = _a(f, "atr")
    rng = h - l
    body = np.abs(c - o)
    pos = np.where(rng > 0, (c - l) / np.where(rng > 0, rng, 1), 0.5)  # 0 = cierre en el mínimo
    relvol = _a(f, "relvol")
    k, d = _a(f, "stoch_k"), _a(f, "stoch_d")
    pk, pd_ = _prev(k), _prev(d)
    hist = _a(f, "macd_hist")
    r2, r7 = _a(f, "rsi2"), _a(f, "rsi7")
    pr7 = _prev(r7)
    cci = _a(f, "cci")
    pcci = _prev(cci)
    st = _a(f, "st_dir")
    pst = _prev(st)
    adx, pdi, ndi = _a(f, "adx"), _a(f, "pdi"), _a(f, "ndi")
    ppdi, pndi = _prev(pdi), _prev(ndi)
    bbu, bbl, bwp = _a(f, "bb_up"), _a(f, "bb_lo"), _a(f, "bb_bw_pct")
    kcu, kcl = _a(f, "kc_up"), _a(f, "kc_lo")
    pkcu, pkcl, pbbu, pbbl, pbwp = _prev(kcu), _prev(kcl), _prev(bbu), _prev(bbl), _prev(bwp)
    dh, dl = _a(f, "don_hi"), _a(f, "don_lo")
    pdh, pdl, onh, onl, orh, orl = (_a(f, x) for x in ("pdh", "pdl", "onh", "onl", "orh", "orl"))
    xl, xh, xll, xhh = _a(f, "x_low"), _a(f, "x_high"), _a(f, "x_ll20"), _a(f, "x_hh20")
    xok = f["x_ok"].to_numpy(dtype=bool)
    above5 = (f["close"] - f["vwap"]).shift(1).rolling(5).min().to_numpy(dtype=np.float64) > 0
    below5 = (f["close"] - f["vwap"]).shift(1).rolling(5).max().to_numpy(dtype=np.float64) < 0
    inside = (ph <= _prev(ph)) & (pl >= _prev(pl))
    lower_wick = np.minimum(o, c) - l
    upper_wick = h - np.maximum(o, c)

    t = {}
    t["EMA 9 pullback en tendencia"] = (
        (e9 > e21) & (e21 > e50) & (l <= e9) & (c > e9),
        (e9 < e21) & (e21 < e50) & (h >= e9) & (c < e9))
    t["Recupera VWAP"] = ((c > vw) & (pc <= pvw), (c < vw) & (pc >= pvw))
    t["Retroceso a VWAP en tendencia"] = (above5 & (l <= vw) & (c > vw), below5 & (h >= vw) & (c < vw))
    t["Rechazo banda VWAP 2σ"] = ((l <= vw - 2 * sd) & (c > vw - 2 * sd), (h >= vw + 2 * sd) & (c < vw + 2 * sd))
    t["Rechazo banda VWAP 1σ"] = ((l <= vw - sd) & (c > vw - sd) & (c < vw), (h >= vw + sd) & (c < vw + sd) & (c > vw))
    t["Barrido de swing (liquidez)"] = (f["sweep_bull"].to_numpy(bool), f["sweep_bear"].to_numpy(bool))
    t["Barrido del día anterior"] = ((l < pdl) & (c > pdl), (h > pdh) & (c < pdh))
    t["Barrido de la noche (ON)"] = ((l < onl) & (c > onl), (h > onh) & (c < onh))
    t["Ruptura rango apertura 15m"] = ((c > orh) & (pc <= orh), (c < orl) & (pc >= orl))
    t["Falsa ruptura rango apertura"] = ((l < orl) & (c > orl), (h > orh) & (c < orh))
    t["Reentrada Bollinger"] = ((pc < pbbl) & (c > bbl), (pc > pbbu) & (c < bbu))
    t["Ruptura squeeze Bollinger"] = ((pbwp < 0.2) & (c > bbu), (pbwp < 0.2) & (c < bbl))
    t["Ruptura Keltner"] = ((c > kcu) & (pc <= pkcu), (c < kcl) & (pc >= pkcl))
    t["Ruptura Donchian 20"] = (c > dh, c < dl)
    t["Estocástico cruza en extremo"] = ((pk <= pd_) & (k > d) & (pk < 20), (pk >= pd_) & (k < d) & (pk > 80))
    t["MACD histograma cruza 0"] = ((_prev(hist) <= 0) & (hist > 0), (_prev(hist) >= 0) & (hist < 0))
    t["RSI(2) extremo"] = (r2 < 5, r2 > 95)
    t["RSI(7) sale de 30/70"] = ((pr7 <= 30) & (r7 > 30), (pr7 >= 70) & (r7 < 70))
    t["CCI sale de ±100"] = ((pcci <= -100) & (cci > -100), (pcci >= 100) & (cci < 100))
    t["Supertrend cambia"] = ((pst == -1) & (st == 1), (pst == 1) & (st == -1))
    t["ADX>25 + cruce DI"] = ((adx > 25) & (ppdi <= pndi) & (pdi > ndi), (adx > 25) & (pndi <= ppdi) & (ndi > pdi))
    t["Envolvente"] = ((pc < po) & (c > o) & (c >= po) & (o <= pc), (pc > po) & (c < o) & (c <= po) & (o >= pc))
    t["Martillo / estrella"] = (
        (lower_wick >= 2 * body) & (lower_wick >= 0.6 * rng) & (rng > 0.5 * a),
        (upper_wick >= 2 * body) & (upper_wick >= 0.6 * rng) & (rng > 0.5 * a))
    t["Ruptura de inside bar"] = (inside & (c > ph), inside & (c < pl))
    t["Clímax de volumen (reversión)"] = ((relvol > 2.5) & (l < dl) & (pos > 0.5), (relvol > 2.5) & (h > dh) & (pos < 0.5))
    t["Divergencia SMT"] = (xok & (l < dl) & (xl > xll), xok & (h > dh) & (xh < xhh))
    t["Vela de impulso"] = ((rng > 2 * a) & (pos > 0.75) & (relvol > 1.5), (rng > 2 * a) & (pos < 0.25) & (relvol > 1.5))
    return {k: (np.nan_to_num(v[0], nan=0).astype(bool), np.nan_to_num(v[1], nan=0).astype(bool)) for k, v in t.items()}


def filters(f):
    c = _a(f, "close")
    e9, e21, e50, e200 = (_a(f, k) for k in ("ema9", "ema21", "ema50", "ema200"))
    vw, sd = _a(f, "vwap"), _a(f, "vwap_sd")
    m = f["minutes"].to_numpy()
    a, amed = _a(f, "atr"), _a(f, "atr_med")
    both = lambda x: (x, x)  # noqa: E731  filtros sin dirección (hora, volatilidad, volumen)
    fl = {}
    fl["Sobre/bajo EMA 200"] = (c > e200, c < e200)
    fl["EMAs 9>21>50 alineadas"] = ((e9 > e21) & (e21 > e50), (e9 < e21) & (e21 < e50))
    fl["Lado del VWAP a favor"] = (c > vw, c < vw)
    fl["Estirado >1σ del VWAP en contra"] = (c < vw - sd, c > vw + sd)
    fl["Régimen 15m a favor"] = (_a(f, "reg15") == 1, _a(f, "reg15") == -1)
    fl["Régimen 1h a favor"] = (_a(f, "reg1h") == 1, _a(f, "reg1h") == -1)
    fl["Bias diario a favor"] = (_a(f, "reg1d") == 1, _a(f, "reg1d") == -1)
    fl["Hora: apertura 9:35-11:00"] = both(m < 660)
    fl["Hora: mediodía 11:00-14:00"] = both((m >= 660) & (m < 840))
    fl["Hora: cierre 14:00-15:45"] = both(m >= 840)
    fl["Volumen relativo >1,5"] = both(_a(f, "relvol") > 1.5)
    fl["ADX > 25"] = both(_a(f, "adx") > 25)
    fl["Volatilidad alta"] = both(a > 1.2 * amed)
    fl["Volatilidad baja"] = both(a < 0.8 * amed)
    fl["RSI(14) a favor de 50"] = (_a(f, "rsi14") > 50, _a(f, "rsi14") < 50)
    fl["Día a favor (vs apertura)"] = (c > _a(f, "rth_open"), c < _a(f, "rth_open"))
    fl["Gap a favor"] = (_a(f, "rth_open") > _a(f, "pdc"), _a(f, "rth_open") < _a(f, "pdc"))
    fl["Mercado hermano a favor del VWAP"] = (_a(f, "x_close") > _a(f, "x_vwap"), _a(f, "x_close") < _a(f, "x_vwap"))
    return {k: (np.nan_to_num(v[0], nan=0).astype(bool), np.nan_to_num(v[1], nan=0).astype(bool)) for k, v in fl.items()}
