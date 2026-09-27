"""
Genera los gráficos de REPORT.md (img/*.png) a partir de results/*.csv.
Ejecutar después de study_correlations.py, study_setups.py, study_mtf.py y study_robust.py.
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
IMG = os.path.join(HERE, "img")

SURFACE = "#fcfcfb"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0"
BLUE, ORANGE, RED, GRAY = "#2a78d6", "#eb6834", "#e34948", "#c9c8c2"
DIVERGING = LinearSegmentedColormap.from_list("div", ["#b8322f", "#e34948", "#f3b9b3", "#f0efec", "#9ec5f4", "#2a78d6", "#1c5cab"])
SHORT = {"NAS100_USD": "NQ", "SPX500_USD": "ES", "US2000_USD": "RTY", "XAU_USD": "Oro", "EUR_USD": "EUR/USD", "WTICO_USD": "Petróleo"}
ORDER = list(SHORT)
INDICES = ["NAS100_USD", "SPX500_USD", "US2000_USD"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "legend.frameon": False,
})


def save(fig, name):
    os.makedirs(IMG, exist_ok=True)
    fig.savefig(os.path.join(IMG, name), dpi=150, bbox_inches="tight")
    plt.close(fig)


def subtitle(ax, text):
    ax.text(0, 1.02, text, transform=ax.transAxes, color=INK2, fontsize=9, va="bottom")


def fig_redundancy():
    fc = pd.read_csv(os.path.join(RES, "feature_corr.csv"))
    s = fc[fc.a == "rsi14"].groupby("b").rho.mean().drop("rsi14").sort_values()
    labels = {"d21": "Distancia a EMA 21 (en ATR)", "d50": "Distancia a EMA 50", "slope21": "Pendiente EMA 21",
              "gap_9_21": "Separación EMA 9 – EMA 21", "d200": "Distancia a EMA 200", "rsi2": "RSI(2)"}
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    y = np.arange(len(s))
    ax.barh(y, s.values, height=0.5, color=BLUE)
    for yi, v in zip(y, s.values):
        ax.text(v + 0.01, yi, f"{v:.2f}", va="center", color=INK, fontsize=9)
    ax.set_yticks(y, [labels[k] for k in s.index])
    ax.set_xlim(0, 1.08)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Correlación de rango (Spearman) con RSI(14)")
    ax.set_title("El RSI(14) y la distancia a la EMA 21 son casi el mismo dato", pad=22)
    subtitle(ax, "Media de 6 mercados × 4 timeframes, 2005–2020")
    save(fig, "1_redundancia.png")


def fig_ic_heatmap():
    ic = pd.read_csv(os.path.join(RES, "ic.csv"))
    mid = {"5m": 6, "15m": 4, "1h": 6, "1d": 5}
    rows = []
    for tf, h in mid.items():
        s = ic[(ic.regime == "Todos") & (ic.tf == tf) & (ic.h == h) & (ic.feature == "rsi14")]
        rows.append(s.set_index("inst").ic.rename(tf))
    m = pd.concat(rows, axis=1).loc[ORDER] * 100
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    lim = 7
    ax.imshow(m.values, cmap=DIVERGING, vmin=-lim, vmax=lim, aspect="auto")
    ax.grid(False)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            v = m.values[i, j]
            ax.text(j, i, f"{v:+.1f}", ha="center", va="center", fontsize=9, color="#ffffff" if abs(v) > 4.5 else INK)
    ax.set_xticks(range(4), ["5m\n(30 min)", "15m\n(1 h)", "1h\n(6 h)", "Diario\n(1 semana)"])
    ax.set_yticks(range(len(m)), [SHORT[k] for k in m.index])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("¿El RSI alto anticipa subidas (azul) o caídas (rojo)?", pad=22)
    subtitle(ax, "IC = correlación de rango RSI(14) vs. retorno futuro, ×100. Horizonte entre paréntesis")
    save(fig, "2_rsi_segun_timeframe.png")


def fig_rsi_regime():
    c = pd.read_csv(os.path.join(RES, "rsi_regime.csv"))
    c = c[c.inst.isin(INDICES) & c.regime.isin(["Alcista", "Bajista"])]
    bins = ["(-0.001, 20.0]", "(20.0, 30.0]", "(30.0, 40.0]", "(40.0, 50.0]", "(50.0, 60.0]", "(60.0, 70.0]", "(70.0, 80.0]", "(80.0, 100.0]"]
    names = ["<20", "20–30", "30–40", "40–50", "50–60", "60–70", "70–80", ">80"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9), sharey=False)
    for ax, tf, title in ((axes[0], "15m", "15 minutos (próximas 4 velas = 1 h)"), (axes[1], "1h", "1 hora (próximas 6 velas = 6 h)")):
        for reg, col in (("Alcista", BLUE), ("Bajista", ORANGE)):
            s = c[(c.tf == tf) & (c.regime == reg)]
            g = s.groupby("rsi_bin").apply(lambda d: pd.Series({"edge": np.average(d.edge, weights=d.n), "n": d.n.sum()}),
                                           include_groups=False)
            g = g.reindex(bins)
            ok = g.n >= 60
            x = np.arange(len(bins))[ok.values]
            ax.plot(x, g.edge[ok] * 100, color=col, lw=2, marker="o", ms=6, mec=SURFACE, mew=2,
                    label=f"Tendencia {reg.lower()} (EMA 50/200)", solid_capstyle="round")
        ax.axhline(0, color=MUTED, lw=1)
        ax.set_xticks(range(len(bins)), names)
        ax.set_xlabel("RSI(14) de la vela actual")
        ax.set_title(title, fontsize=11)
    axes[0].set_ylabel("Retorno futuro vs. media\n(centésimas de ATR)")
    axes[0].legend(loc="upper left", fontsize=9)
    fig.suptitle("En 15m el RSI extremo continúa a favor de la tendencia; en 1h ya se agota", x=0.01, ha="left",
                 fontsize=12, fontweight="bold", y=1.04)
    fig.text(0.01, 0.97, "NQ + ES + RTY, 2005–2020. Tramos con menos de 60 casos omitidos", color=INK2, fontsize=9)
    save(fig, "3_rsi_por_regimen.png")


def fig_costs():
    r = pd.read_csv(os.path.join(RES, "setups.csv"))
    r = r[r.inst.isin(INDICES) & (r.exit == "nativa")]
    g = r.groupby("tf")[["avgR_gross", "avgR"]].mean().reindex(["5m", "15m", "1h", "1d"])
    fig, ax = plt.subplots(figsize=(7, 3.8))
    x = np.arange(4)
    w = 0.34
    ax.bar(x - w / 2 - 0.01, g.avgR_gross, width=w, color=BLUE, label="Antes de costos")
    ax.bar(x + w / 2 + 0.01, g.avgR, width=w, color=ORANGE, label="Después de costos")
    for xi, v in zip(x, g.avgR):
        ax.text(xi + w / 2 + 0.01, v - 0.012 if v < 0 else v + 0.004, f"{v:+.2f}R", ha="center",
                va="top" if v < 0 else "bottom", fontsize=9, color=INK)
    ax.axhline(0, color=MUTED, lw=1)
    ax.set_xticks(x, ["5m", "15m", "1h", "Diario"])
    ax.set_ylim(g.min().min() - 0.03, max(g.max().max(), 0) + 0.02)
    ax.set_ylabel("Resultado medio por operación (R)")
    ax.legend(loc="lower right", fontsize=9)
    ax.set_title("Los costos, no los indicadores, hunden el trading en 5m", pad=22)
    subtitle(ax, "Promedio de los 7 setups clásicos, largos y cortos, en NQ/ES/RTY")
    save(fig, "4_costos_por_timeframe.png")


def fig_swing_vs_random():
    c = pd.read_csv(os.path.join(RES, "swing_control.csv")).set_index("inst").loc[ORDER[::-1]]
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    y = np.arange(len(c))
    for yi, a, b in zip(y, c.random_avgR, c.avgR):
        ax.plot([a, b], [yi, yi], color=GRAY, lw=2, zorder=1)
    ax.scatter(c.random_avgR, y, s=64, color=ORANGE, edgecolor=SURFACE, linewidth=2, zorder=2,
               label="Mismo filtro y salida, entrada al azar")
    ax.scatter(c.avgR, y, s=64, color=BLUE, edgecolor=SURFACE, linewidth=2, zorder=3, label="RSI(2) < 10 sobre EMA 200")
    for yi, v, w in zip(y, c.avgR, c.win):
        ax.text(max(v, 0.03) + 0.012, yi, f"{v:+.2f}R · {w:.0f}% aciertos", va="center", fontsize=9, color=INK)
    ax.axvline(0, color=MUTED, lw=1)
    ax.set_yticks(y, [SHORT[k] for k in c.index])
    ax.set_xlim(-0.07, 0.34)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Resultado medio por operación, neto de costos (R)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, fontsize=9)
    ax.set_title("Swing diario: el RSI(2) le gana al azar en índices y oro", pad=22)
    subtitle(ax, "Largos, 2005–2020. Azar = media de 200 simulaciones con la misma frecuencia")
    save(fig, "5_swing_vs_azar.png")


def fig_swing_equity():
    t = pd.read_csv(os.path.join(RES, "swing_trades.csv"))
    t["entry_time"] = pd.to_datetime(t.entry_time)
    fig, ax = plt.subplots(figsize=(9, 4))
    for inst, col in zip(INDICES, [BLUE, ORANGE, "#1baf7a"]):
        s = t[t.inst == inst].sort_values("entry_time")
        eq = s.R.cumsum()
        ax.step(s.entry_time, eq, where="post", color=col, lw=2, label=SHORT[inst])
        ax.text(s.entry_time.iloc[-1], eq.iloc[-1], f"  {SHORT[inst]} {eq.iloc[-1]:+.0f}R", color=INK, fontsize=9, va="center")
    ax.axhline(0, color=MUTED, lw=1)
    ax.set_ylabel("R acumulados (neto de costos)")
    ax.legend(loc="upper left", fontsize=9)
    ax.set_title("Swing RSI(2) diario en índices, 2005–2020", pad=22)
    subtitle(ax, "RSI(2) < 10 con cierre sobre EMA 200 · salida al cerrar sobre la EMA 5 · stop 2 ATR · máx. 20 días")
    ax.margins(x=0.1)
    save(fig, "6_curva_swing.png")


def fig_lookahead():
    c = pd.read_csv(os.path.join(RES, "lookahead.csv"))
    ok = c[c.version == "correcto"].set_index("inst").loc[ORDER[::-1]]
    bad = c[c.version != "correcto"].set_index("inst").loc[ORDER[::-1]]
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    y = np.arange(len(ok))
    for yi, a, b in zip(y, ok.avgR, bad.avgR):
        ax.plot([a, b], [yi, yi], color=GRAY, lw=2, zorder=1)
    ax.scatter(bad.avgR, y, s=64, color=ORANGE, edgecolor=SURFACE, linewidth=2, zorder=2, label="Con 1 hora de información futura")
    ax.scatter(ok.avgR, y, s=64, color=BLUE, edgecolor=SURFACE, linewidth=2, zorder=3, label="Correcto")
    ax.axvline(0, color=MUTED, lw=1)
    ax.set_yticks(y, [SHORT[k] for k in ok.index])
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Resultado medio por operación, neto de costos (R)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, fontsize=9)
    ax.set_title(f"Un error de 1 hora convierte {ok.totR.sum():+.0f}R en {bad.totR.sum():+.0f}R", pad=22)
    subtitle(ax, "Mismo sistema intradía (semáforo 1h+diario + RSI 15m), mismas operaciones salvo el error")
    save(fig, "7_error_look_ahead.png")


def fig_confirmations():
    c = pd.read_csv(os.path.join(RES, "confirm_effects.csv")).iloc[::-1]
    fig, ax = plt.subplots(figsize=(7.8, 3.9))
    y = np.arange(len(c))
    ax.barh(y, c.delta_bruto, height=0.5, color=BLUE, xerr=2 * c.se, ecolor=INK2, capsize=3,
            error_kw=dict(lw=1))
    for yi, d, keep, imp in zip(y, c.delta_bruto, c.trades_ratio, c.mejora_pct):
        ax.text(0.03, yi, f"quedan {keep * 100:.0f}% de las operaciones · mejora en {imp:.0f}% de los casos",
                va="center", fontsize=8.5, color=INK2)
    ax.axvline(0, color=MUTED, lw=1)
    ax.set_yticks(y, c.confirm)
    ax.set_xlim(-0.06, 0.16)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Cambio en el resultado medio por operación ANTES de costos (R), ±2 errores estándar")
    ax.set_title("Las confirmaciones filtran operaciones, pero no las mejoran", pad=22)
    subtitle(ax, "Setup base: EMA 25 y 50 cruzan la 200 → apoyo en la EMA. 5m/15m/1h, 6 mercados, pares idénticos salvo la confirmación")
    save(fig, "8_confirmaciones.png")


if __name__ == "__main__":
    fig_redundancy()
    fig_ic_heatmap()
    fig_rsi_regime()
    fig_costs()
    fig_swing_vs_random()
    fig_swing_equity()
    fig_lookahead()
    fig_confirmations()
    print("ok ->", IMG)
