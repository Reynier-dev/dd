"""Gráficos del informe de scalping (img/*.png) a partir de results/*.csv."""
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ema_rsi"))
from make_figures import BLUE, GRAY, INK, INK2, MUTED, ORANGE, RED, SURFACE, save as _save, subtitle  # noqa: E402,F401

from features import COST_MARKET  # noqa: E402

RES = os.path.join(HERE, "results")
IMG = os.path.join(HERE, "img")
SHORT = {"NAS100_USD": "NQ", "SPX500_USD": "ES", "US2000_USD": "RTY"}


def save(fig, name):
    os.makedirs(IMG, exist_ok=True)
    fig.savefig(os.path.join(IMG, name), dpi=150, bbox_inches="tight")
    plt.close(fig)


def fig_cost_barrier():
    c = pd.read_csv(os.path.join(RES, "cost_barrier.csv"))
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.6), sharey=True)
    for ax, inst in zip(axes, SHORT):
        s = c[c.inst == inst]
        x = np.arange(3)
        w = 0.36
        m = s[s.exec == "mercado"].set_index("tf").loc[["1m", "3m", "5m"]]
        lim = s[s.exec == "límite"].set_index("tf").loc[["1m", "3m", "5m"]]
        ax.bar(x - w / 2 - 0.01, m.net_R, width=w, color=ORANGE, label="Orden a mercado")
        ax.bar(x + w / 2 + 0.01, lim.net_R, width=w, color=BLUE, label="Orden límite")
        for xi, v in zip(x, m.net_R):
            ax.text(xi - w / 2 - 0.01, v - 0.02, f"{v:.2f}", ha="center", va="top", fontsize=8.5, color=INK)
        ax.axhline(0, color=MUTED, lw=1)
        ax.set_xticks(x, ["1m", "3m", "5m"])
        ax.set_title(SHORT[inst], fontsize=11)
        ax.set_ylim(-1.05, 0.05)
    axes[0].set_ylabel("Resultado por operación (R)")
    axes[0].legend(loc="lower right", fontsize=8.5)
    fig.suptitle("La barrera: lo que pierde una entrada al azar solo por costos", x=0.01, ha="left",
                 fontsize=12, fontweight="bold", y=1.05)
    fig.text(0.01, 0.98, "Stop y objetivo de 1 ATR, comisión USD 4,50 + 1 tick por lado a mercado, 2008-2013",
             color=INK2, fontsize=9)
    save(fig, "1_barrera_costos.png")


def fig_gross_vs_cost():
    r = pd.read_csv(os.path.join(RES, "scan.csv.gz"), usecols=["inst", "trigger", "gross_d", "n_d", "tf"])
    r = r[(~r.trigger.str.startswith("Control")) & (r.n_d >= 300)]
    ratio = (r.gross_d / r.inst.map(COST_MARKET)).clip(-3, 3)
    fig, ax = plt.subplots(figsize=(8, 3.6))
    bins = np.linspace(-3, 3, 61)
    ax.hist(ratio[ratio < 1], bins=bins, color=GRAY)
    ax.hist(ratio[ratio >= 1], bins=bins, color=BLUE)
    ax.axvline(1, color=INK, lw=1)
    share = (ratio >= 1).mean() * 100
    ax.text(1.05, ax.get_ylim()[1] * 0.85, f"cubren el costo:\n{share:.1f}% de las combinaciones".replace(".", ","), fontsize=9, color=INK)
    ax.set_xlabel("Ventaja bruta por operación ÷ costo por operación")
    ax.set_ylabel("Combinaciones")
    ax.grid(axis="x", visible=False)
    ax.set_title("Casi ninguna combinación gana más de lo que cuesta operarla", pad=22)
    subtitle(ax, f"{len(r):,} combinaciones gatillo × confirmaciones × horizonte".replace(",", ".") + " · NQ/ES/RTY 1m-5m, 2008-2013")
    save(fig, "2_ventaja_vs_costo.png")


def fig_overlap():
    r = pd.read_csv(os.path.join(RES, "scan_recheck.csv")).sort_values("t_d")
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    y = np.arange(len(r))
    for yi, a, b in zip(y, r.tclu_d, r.t_d):
        ax.plot([a, b], [yi, yi], color=GRAY, lw=1.2, zorder=1)
    ax.scatter(r.t_d, y, s=16, color=ORANGE, zorder=2, label="Contando cada vela como independiente")
    ax.scatter(r.tclu_d, y, s=16, color=BLUE, zorder=3, label="Agrupando por día (correcto)")
    ax.axvline(3, color=INK, lw=1)
    ax.text(3.05, len(r) - 2, "umbral t = 3", fontsize=8.5, color=INK2)
    ax.set_yticks([])
    ax.set_xlabel("t-stat neto de costos (descubrimiento 2008-2013)")
    ax.legend(loc="lower right", fontsize=8.5)
    ax.set_title(f"Los {len(r)} 'ganadores' del escaneo eran una ilusión del solapamiento", pad=22)
    subtitle(ax, "Cada línea es una combinación. Corregido, ninguna llega a t = 3")
    save(fig, "3_ilusion_solapamiento.png")


if __name__ == "__main__":
    for fn in sys.argv[1:] or ["fig_cost_barrier", "fig_gross_vs_cost", "fig_overlap"]:
        globals()[fn]()
    print("ok ->", IMG)
