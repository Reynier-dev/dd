"""
Simulador de scalping con trayectoria de 1 minuto.

La señal se evalúa al cierre de la vela del timeframe de trabajo (1m, 3m o 5m); la orden se
gestiona recorriendo las velas de 1 minuto siguientes:

  modo 0 "mercado": entrada en la apertura del primer minuto después de la señal, con 1 tick
          de deslizamiento.
  modo 1 "límite":  orden límite en el cierre de la vela de señal menos `offset` ATR, válida
          `limit_minutes`. Solo se llena si el precio ATRAVIESA el límite por al menos 1 tick
          (supuesto conservador de cola). Sin deslizamiento en la entrada.

Salidas: stop (orden stop a mercado, 1 tick de deslizamiento o la apertura si hay hueco),
objetivo (orden límite; se llena solo si el precio lo atraviesa por 1 tick), tiempo máximo o
cierre de la sesión regular (a mercado, 1 tick de deslizamiento). Si stop y objetivo caben en el
mismo minuto, se asume el stop. En el minuto en que se llena una orden límite solo se revisa el
stop. Comisión en cada operación. Una posición a la vez.
"""
import numpy as np
import pandas as pd
from numba import njit

from features import COMMISSION, TICK, TF_MIN, load, session_frame


@njit(cache=True)
def _run(o, h, l, c, day_last, entry_idx, limit_px, risk, direction,
         stop_mult, tgt_mult, max_minutes, mode, limit_minutes, tick, commission):
    n_sig = len(entry_idx)
    out_entry = np.full(n_sig, -1, np.int64)
    out_exit = np.full(n_sig, -1, np.int64)
    out_pts = np.full(n_sig, np.nan)
    out_kind = np.zeros(n_sig, np.int64)  # 1 stop, 2 objetivo, 3 tiempo, 4 cierre de sesión
    busy_until = -1
    for s in range(n_sig):
        e = entry_idx[s]
        if e < 0 or e <= busy_until:
            continue
        last = day_last[e]
        if last < 0 or e >= last:
            continue
        # --- entrada
        if mode == 0:
            fill_i = e
            px = o[e] + direction * tick
        else:
            fill_i = -1
            px = limit_px[s]
            j = e
            while j <= last and j < e + limit_minutes:
                if direction == 1 and l[j] <= px - tick:
                    fill_i = j
                    px = min(px, o[j])
                    break
                if direction == -1 and h[j] >= px + tick:
                    fill_i = j
                    px = max(px, o[j])
                    break
                j += 1
            if fill_i < 0:
                busy_until = e + limit_minutes - 1
                continue
        r = risk[s]
        stop = px - direction * stop_mult * r
        tgt = px + direction * tgt_mult * r
        # --- gestión
        j = fill_i
        x = np.nan
        kind = 0
        while True:
            if direction == 1:
                if l[j] <= stop:
                    x = (stop if j == fill_i else min(o[j], stop)) - tick
                    kind = 1
                    break
                if j > fill_i or mode == 0:
                    if h[j] >= tgt + tick:
                        x = tgt
                        kind = 2
                        break
            else:
                if h[j] >= stop:
                    x = (stop if j == fill_i else max(o[j], stop)) + tick
                    kind = 1
                    break
                if j > fill_i or mode == 0:
                    if l[j] <= tgt - tick:
                        x = tgt
                        kind = 2
                        break
            if j >= last:
                x = c[j] - direction * tick
                kind = 4
                break
            if j - fill_i + 1 >= max_minutes:
                x = c[j] - direction * tick
                kind = 3
                break
            j += 1
        out_entry[s] = fill_i
        out_exit[s] = j
        out_pts[s] = direction * (x - px) - commission
        out_kind[s] = kind
        busy_until = j
    return out_entry, out_exit, out_pts, out_kind


class Minute:
    """Velas de 1 minuto de un mercado, con la posición de la última vela RTH de cada día."""

    def __init__(self, inst):
        m = load(inst, "1m")
        s = session_frame(m, "1m")
        self.index = m.index
        self.o = m["open"].to_numpy(np.float64)
        self.h = m["high"].to_numpy(np.float64)
        self.l = m["low"].to_numpy(np.float64)
        self.c = m["close"].to_numpy(np.float64)
        self.day_last = s["last_rth_pos"].to_numpy(np.int64)
        self.tick = TICK[inst]
        self.commission = COMMISSION[inst]


def simulate(minute, f, tf, signal_pos, direction, stop_mult, tgt_mult, max_bars,
             mode=0, offset=0.0, limit_bars=2):
    """signal_pos: posiciones (en el DataFrame de features del TF) de las velas de señal."""
    step = pd.Timedelta(minutes=TF_MIN[tf])
    entry_times = f.index[signal_pos] + step
    entry_idx = np.searchsorted(minute.index.values, entry_times.values)
    entry_idx = np.where(entry_idx < len(minute.index), entry_idx, -1)
    # la vela de 1m encontrada tiene que pertenecer al mismo día RTH que la señal
    ok = entry_idx >= 0
    same_day = np.zeros(len(entry_idx), bool)
    same_day[ok] = (minute.index[entry_idx[ok]].normalize() == f.index[signal_pos][ok].normalize())
    entry_idx = np.where(same_day, entry_idx, -1)
    atr = f["atr"].to_numpy(np.float64)[signal_pos]
    close = f["close"].to_numpy(np.float64)[signal_pos]
    limit_px = close - direction * offset * atr
    res = _run(minute.o, minute.h, minute.l, minute.c, minute.day_last, entry_idx.astype(np.int64),
               limit_px, atr, direction, stop_mult, tgt_mult, max_bars * TF_MIN[tf], mode,
               limit_bars * TF_MIN[tf], minute.tick, minute.commission)
    e, x, pts, kind = res
    done = e >= 0
    return pd.DataFrame({"signal_time": f.index[signal_pos][done], "entry_time": minute.index[e[done]],
                         "exit_time": minute.index[x[done]], "pts": pts[done], "kind": kind[done],
                         "risk_pts": stop_mult * atr[done]})
