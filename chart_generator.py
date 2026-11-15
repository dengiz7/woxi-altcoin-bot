# -*- coding: utf-8 -*-
"""
Altcoin Bot Tarzı Karanlık Temalı 4H WaveTrend Grafik Üreticisi
"""

from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def generate_wavetrend_chart(
    symbol: str,
    direction: str,
    wt1: np.ndarray,
    wt2: np.ndarray,
    output_path: Path,
    lookback: int = 100,
) -> Optional[Path]:
    """
    Son `lookback` mumluk 4H WaveTrend grafiğini Bull/Bear kesişim etiketleriyle PNG olarak kaydeder.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        n = min(len(wt1), len(wt2), lookback)
        if n < 15:
            return None

        w1 = np.asarray(wt1[-n:], dtype=float)
        w2 = np.asarray(wt2[-n:], dtype=float)
        x = np.arange(n)

        fig, ax = plt.subplots(figsize=(16, 6.2), dpi=100)
        bg = "#0d1117"
        fig.patch.set_facecolor(bg)
        ax.set_facecolor(bg)

        # Yatay referans çizgileri (+60, 0, -50, -60)
        ax.axhline(60, color="#ef5350", linestyle="--", linewidth=1.0, alpha=0.55)
        ax.axhline(0, color="#6e7681", linestyle="-", linewidth=0.9, alpha=0.6)
        ax.axhline(-50, color="#26a69a", linestyle="--", linewidth=1.0, alpha=0.55)
        ax.axhline(-60, color="#26a69a", linestyle=":", linewidth=0.9, alpha=0.45)

        # WT1 eğimine göre renkli çizgi (yükselirken turkuaz, düşerken kırmızımsı)
        for i in range(1, n):
            seg_color = "#26a69a" if w1[i] >= w1[i - 1] else "#ef5350"
            ax.plot(x[i - 1:i + 1], w1[i - 1:i + 1], color=seg_color, linewidth=2.2, zorder=3)

        # WT2 çizgisi (turuncu)
        ax.plot(x, w2, color="#e67e22", linewidth=1.8, alpha=0.9, zorder=2)

        # Kesişim noktalarını bul ve etiketle
        for i in range(1, n):
            is_last = (i == n - 1)
            bull_cross = w1[i - 1] <= w2[i - 1] and w1[i] > w2[i]
            bear_cross = w1[i - 1] >= w2[i - 1] and w1[i] < w2[i]

            if bull_cross and (w1[i] <= -15 or is_last):
                ms = 17 if is_last else 11
                ec = "#ffd600" if is_last else "#ffffff"
                lw = 2.4 if is_last else 1.2
                ax.plot(
                    x[i], w1[i],
                    marker="^", markersize=ms,
                    markerfacecolor="#00bfa5", markeredgecolor=ec, markeredgewidth=lw,
                    zorder=5,
                )
                ax.annotate(
                    "Bull",
                    xy=(x[i], w1[i]),
                    xytext=(0, -22),
                    textcoords="offset points",
                    ha="center", va="top",
                    fontsize=9.5 if is_last else 8.5,
                    fontweight="bold",
                    color="#ffffff",
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="#00897b", edgecolor="none", alpha=0.92),
                    zorder=6,
                )
            elif bear_cross and (w1[i] >= 15 or is_last):
                ms = 17 if is_last else 11
                ec = "#ffd600" if is_last else "#ffffff"
                lw = 2.4 if is_last else 1.2
                ax.plot(
                    x[i], w1[i],
                    marker="v", markersize=ms,
                    markerfacecolor="#e53935", markeredgecolor=ec, markeredgewidth=lw,
                    zorder=5,
                )
                ax.annotate(
                    "Bear",
                    xy=(x[i], w1[i]),
                    xytext=(0, 22),
                    textcoords="offset points",
                    ha="center", va="bottom",
                    fontsize=9.5 if is_last else 8.5,
                    fontweight="bold",
                    color="#ffffff",
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="#c62828", edgecolor="none", alpha=0.92),
                    zorder=6,
                )

        # Görünüm ve başlık
        signal_tag = "BULL SIGNAL" if direction == "LONG" else "BEAR SIGNAL"
        ax.set_title(
            f"{symbol} - WaveTrend {signal_tag} (4H)",
            color="#e6edf3",
            fontsize=15,
            fontweight="bold",
            pad=14,
        )
        y_min = min(-82.0, float(np.nanmin(w1)) - 12.0)
        y_max = max(82.0, float(np.nanmax(w1)) + 12.0)
        ax.set_ylim(y_min, y_max)
        ax.set_xlim(-2, n + 2)
        ax.tick_params(axis="y", colors="#8b949e", labelsize=10)
        ax.tick_params(axis="x", which="both", bottom=False, labelbottom=False)
        for spine in ("top", "right", "bottom"):
            ax.spines[spine].set_visible(False)
        ax.spines["left"].set_color("#30363d")

        plt.tight_layout()
        fig.savefig(str(output_path), facecolor=bg, dpi=100)
        plt.close(fig)
        return output_path
    except Exception as exc:
        print(f"[UYARI] Grafik çizilemedi ({symbol}): {exc}")
        return None
