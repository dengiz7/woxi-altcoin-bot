# -*- coding: utf-8 -*-
"""
Çift Motorlu Strateji Analiz Sistemi:
  1) Engine 1 — ALTCOIN_WT_4H: 4S LazyBear WaveTrend Aşırı Bölge / Uyumsuzluk (4S Trend Yönü Filtreli)
  2) Engine 2 — WOXI_CALMILO: 1H/30m SuperTrend ATR (CALMILO:Trend Line) Kırılımı (4S Trend Yönü Filtreli)
"""

import hashlib
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from bybit_client import Candle
from chart_generator import generate_wavetrend_chart
from config import CHARTS_DIR, Config


@dataclass
class SignalSetup:
    uid: str
    engine: str             # "ALTCOIN_WT_4H" veya "WOXI_CALMILO"
    symbol: str
    timeframe: str          # "4H", "1h", "30m"
    direction: str          # "LONG" veya "SHORT"
    entry_price: float
    sl_price: float
    sl_pct: float
    trend_line: float
    tp1_price: float
    tp2_price: float
    tp3_price: float
    tp4_price: float
    tp1_pct: float
    tp2_pct: float
    tp3_pct: float
    tp4_pct: float
    macro_trend_4h: str     # "UP" veya "DOWN"
    wt_value: float = 0.0
    confidence_pct: int = 85
    is_divergence: bool = False
    is_vip_double: bool = False
    candle_timestamp: int = 0
    chart_path: Optional[str] = None


def _make_uid(prefix: str, symbol: str, timeframe: str, ts: int) -> str:
    raw = f"{prefix}:{symbol}:{timeframe}:{ts}".encode("utf-8")
    digits = str(int(hashlib.sha256(raw).hexdigest()[:12], 16)).zfill(11)[:11]
    return f"{prefix}{digits}"


def calc_ema(values: np.ndarray, period: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    out = np.zeros(n, dtype=float)
    if n == 0:
        return out
    alpha = 2.0 / (period + 1.0)
    out[0] = arr[0]
    for i in range(1, n):
        out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
    return out


def calc_sma(values: np.ndarray, period: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    out = np.zeros(n, dtype=float)
    if n == 0:
        return out
    csum = np.cumsum(arr, dtype=float)
    for i in range(n):
        if i < period - 1:
            out[i] = csum[i] / (i + 1)
        elif i == period - 1:
            out[i] = csum[i] / period
        else:
            out[i] = (csum[i] - csum[i - period]) / period
    return out


def calc_rma(values: np.ndarray, period: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    out = np.zeros(n, dtype=float)
    if n == 0:
        return out
    alpha = 1.0 / period
    out[0] = arr[0]
    for i in range(1, n):
        out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
    return out


def calc_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    if n == 0:
        return np.zeros(0, dtype=float)
    tr = np.zeros(n, dtype=float)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    return calc_rma(tr, period)


def calc_supertrend(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
    mult: float = 3.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    WOXI-BM (CALMILO:Trend Line) ile uyumlu yön ve merdiven gibi takip eden SuperTrend çizgisini döner.
    direction: +1 (Yükseliş / Long bölgesi), -1 (Düşüş / Short bölgesi)
    """
    n = len(close)
    atr = calc_atr(high, low, close, period)
    hl2 = (high + low) / 2.0
    upper_basic = hl2 + mult * atr
    lower_basic = hl2 - mult * atr

    upper_band = np.copy(upper_basic)
    lower_band = np.copy(lower_basic)
    direction = np.ones(n, dtype=int)
    trend_line = np.copy(lower_basic)

    for i in range(1, n):
        # Lower band sadece yükselişte yukarı tırmanır (asla geri inmez)
        if close[i - 1] > lower_band[i - 1]:
            lower_band[i] = max(lower_basic[i], lower_band[i - 1])
        else:
            lower_band[i] = lower_basic[i]

        # Upper band sadece düşüşte aşağı iner (asla geri çıkmaz)
        if close[i - 1] < upper_band[i - 1]:
            upper_band[i] = min(upper_basic[i], upper_band[i - 1])
        else:
            upper_band[i] = upper_basic[i]

        prev_dir = direction[i - 1]
        if prev_dir == -1 and close[i] > upper_band[i - 1]:
            direction[i] = 1
        elif prev_dir == 1 and close[i] < lower_band[i - 1]:
            direction[i] = -1
        else:
            direction[i] = prev_dir

        trend_line[i] = lower_band[i] if direction[i] == 1 else upper_band[i]

    return direction, trend_line


def calc_wavetrend(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    n1: int = Config.WT_N1,
    n2: int = Config.WT_N2,
) -> Tuple[np.ndarray, np.ndarray]:
    """LazyBear WaveTrend Oscillator (WT1, WT2)."""
    ap = (high + low + close) / 3.0
    esa = calc_ema(ap, n1)
    d = calc_ema(np.abs(ap - esa), n1)
    denom = np.maximum(0.015 * d, 1e-12)
    ci = (ap - esa) / denom
    wt1 = calc_ema(ci, n2)
    wt2 = calc_sma(wt1, 4)
    return wt1, wt2


def determine_4h_trend(candles_4h: List[Candle]) -> str:
    """
    4 saatlik kapalı mumlara göre ana makro trend yönünü belirler ("UP", "DOWN", "NEUTRAL").
    """
    closed = [c for c in candles_4h if c.is_closed]
    if len(closed) < 60:
        return "NEUTRAL"

    high = np.array([c.high for c in closed], dtype=float)
    low = np.array([c.low for c in closed], dtype=float)
    close = np.array([c.close for c in closed], dtype=float)

    ema50 = calc_ema(close, 50)
    ema200 = calc_ema(close, min(200, len(close)))
    st_dir, _ = calc_supertrend(high, low, close, period=10, mult=3.0)

    c_last = close[-1]
    if c_last > ema50[-1] and (ema50[-1] >= ema200[-1] or st_dir[-1] == 1):
        return "UP"
    if c_last < ema50[-1] and (ema50[-1] <= ema200[-1] or st_dir[-1] == -1):
        return "DOWN"
    return "NEUTRAL"


def evaluate_altcoin_wt_4h(
    symbol: str,
    candles_4h: List[Candle],
    macro_trend: str,
    generate_chart: bool = True,
) -> Optional[SignalSetup]:
    """
    Engine 1: Altcoin Bot (WaveTrend 4H) — SADECE 4S Ana Trend Yönü ile uyumlu sinyaller!
      - LONG: macro_trend == "UP" ve (WT <= -60 Bull Cross veya Bull Divergence)
      - SHORT: macro_trend == "DOWN" ve (WT >= +60 Bear Cross veya Bear Divergence)
    """
    if macro_trend not in ("UP", "DOWN"):
        return None

    closed = [c for c in candles_4h if c.is_closed]
    if len(closed) < 60:
        return None

    high = np.array([c.high for c in closed], dtype=float)
    low = np.array([c.low for c in closed], dtype=float)
    close = np.array([c.close for c in closed], dtype=float)
    wt1, wt2 = calc_wavetrend(high, low, close, Config.WT_N1, Config.WT_N2)

    prev_w1, curr_w1 = float(wt1[-2]), float(wt1[-1])
    prev_w2, curr_w2 = float(wt2[-2]), float(wt2[-1])
    entry = float(close[-1])
    candle_ts = int(closed[-1].timestamp)

    bull_cross = prev_w1 <= prev_w2 and curr_w1 > curr_w2
    bear_cross = prev_w1 >= prev_w2 and curr_w1 < curr_w2

    direction: Optional[str] = None
    is_div = False

    if macro_trend == "UP" and bull_cross:
        extreme_wt = min(prev_w1, curr_w1)
        if extreme_wt <= Config.WT_OS_LEVEL:
            direction = "LONG"
        elif extreme_wt <= -40.0:
            # Son 30 mumda daha derin (-60 altı) bir dip kesişimi ve fiyat uyumsuzluğu var mı?
            for idx in range(max(2, len(wt1) - 30), len(wt1) - 3):
                if wt1[idx - 1] <= wt2[idx - 1] and wt1[idx] > wt2[idx] and wt1[idx] <= -60.0:
                    if curr_w1 > wt1[idx] and low[-1] <= low[idx] * 1.005:
                        direction = "LONG"
                        is_div = True
                        break

    elif macro_trend == "DOWN" and bear_cross:
        extreme_wt = max(prev_w1, curr_w1)
        if extreme_wt >= Config.WT_OB_LEVEL:
            direction = "SHORT"
        elif extreme_wt >= 40.0:
            for idx in range(max(2, len(wt1) - 30), len(wt1) - 3):
                if wt1[idx - 1] >= wt2[idx - 1] and wt1[idx] < wt2[idx] and wt1[idx] >= 60.0:
                    if curr_w1 < wt1[idx] and high[-1] >= high[idx] * 0.995:
                        direction = "SHORT"
                        is_div = True
                        break

    if not direction:
        return None

    tp1_pct = Config.ALT_TP1_PCT
    tp2_pct = Config.ALT_TP2_PCT
    sl_pct = Config.ALT_SL_PCT

    if direction == "LONG":
        tp1_price = entry * (1.0 + tp1_pct / 100.0)
        tp2_price = entry * (1.0 + tp2_pct / 100.0)
        sl_price = entry * (1.0 - sl_pct / 100.0)
    else:
        tp1_price = entry * (1.0 - tp1_pct / 100.0)
        tp2_price = entry * (1.0 - tp2_pct / 100.0)
        sl_price = entry * (1.0 + sl_pct / 100.0)

    conf = 90 if (abs(curr_w1) >= 70 or is_div) else 85
    chart_path_str: Optional[str] = None
    if generate_chart:
        out_path = CHARTS_DIR / f"{symbol}_wt4h.png"
        saved = generate_wavetrend_chart(symbol, direction, wt1, wt2, out_path)
        if saved:
            chart_path_str = str(saved)

    return SignalSetup(
        uid=_make_uid("ALT", symbol, "4H", candle_ts),
        engine="ALTCOIN_WT_4H",
        symbol=symbol,
        timeframe="4H",
        direction=direction,
        entry_price=entry,
        sl_price=sl_price,
        sl_pct=sl_pct,
        trend_line=entry,
        tp1_price=tp1_price,
        tp2_price=tp2_price,
        tp3_price=tp2_price,
        tp4_price=tp2_price,
        tp1_pct=tp1_pct,
        tp2_pct=tp2_pct,
        tp3_pct=tp2_pct,
        tp4_pct=tp2_pct,
        macro_trend_4h=macro_trend,
        wt_value=round(curr_w1, 1),
        confidence_pct=conf,
        is_divergence=is_div,
        candle_timestamp=candle_ts,
        chart_path=chart_path_str,
    )


def evaluate_woxi_calmilo(
    symbol: str,
    candles: List[Candle],
    timeframe: str,
    macro_trend: str,
) -> Tuple[Optional[SignalSetup], float, int]:
    """
    Engine 2: WOXI-BM (CALMILO:Trend Line) — 1h veya 30m kapanışında SuperTrend kırılımı + 4H Trend Filtresi.
    Her zaman (sinyal_varsa, güncel_trend_çizgisi, güncel_yön) üçlüsünü döner ki aktif işlemlerin
    Trailing Stop seviyeleri her mum kapanışında güncellenebilsin.
    """
    closed = [c for c in candles if c.is_closed]
    if len(closed) < 40:
        return None, 0.0, 0

    high = np.array([c.high for c in closed], dtype=float)
    low = np.array([c.low for c in closed], dtype=float)
    close = np.array([c.close for c in closed], dtype=float)

    st_dir, st_line = calc_supertrend(high, low, close, Config.WOXI_ATR_PERIOD, Config.WOXI_ATR_MULT)
    atr = calc_atr(high, low, close, Config.WOXI_ATR_PERIOD)

    curr_dir = int(st_dir[-1])
    prev_dir = int(st_dir[-2])
    curr_tl = float(st_line[-1])

    direction: Optional[str] = None
    if prev_dir == -1 and curr_dir == 1 and macro_trend == "UP":
        direction = "LONG"
    elif prev_dir == 1 and curr_dir == -1 and macro_trend == "DOWN":
        direction = "SHORT"

    if not direction:
        return None, curr_tl, curr_dir

    entry = float(close[-1])
    candle_ts = int(closed[-1].timestamp)
    delta = max(1.2 * float(atr[-1]), 0.015 * entry)

    raw_sl_dist = 1.25 * abs(entry - curr_tl)
    min_sl_dist = 0.012 * entry
    max_sl_dist = entry * (Config.WOXI_MAX_SL_PCT / 100.0)
    sl_dist = min(max(raw_sl_dist, min_sl_dist), max_sl_dist)

    if direction == "LONG":
        tp1 = entry + 1.0 * delta
        tp2 = entry + 2.0 * delta
        tp3 = entry + 3.0 * delta
        tp4 = entry + 4.5 * delta
        sl_price = entry - sl_dist
    else:
        tp1 = entry - 1.0 * delta
        tp2 = entry - 2.0 * delta
        tp3 = entry - 3.0 * delta
        tp4 = entry - 4.5 * delta
        sl_price = entry + sl_dist

    tp1_pct = round(abs(tp1 - entry) / entry * 100.0, 2)
    tp2_pct = round(abs(tp2 - entry) / entry * 100.0, 2)
    tp3_pct = round(abs(tp3 - entry) / entry * 100.0, 2)
    tp4_pct = round(abs(tp4 - entry) / entry * 100.0, 2)
    sl_pct = round(sl_dist / entry * 100.0, 2)

    setup = SignalSetup(
        uid=_make_uid("UID", symbol, timeframe, candle_ts),
        engine="WOXI_CALMILO",
        symbol=symbol,
        timeframe=timeframe,
        direction=direction,
        entry_price=entry,
        sl_price=sl_price,
        sl_pct=sl_pct,
        trend_line=curr_tl,
        tp1_price=tp1,
        tp2_price=tp2,
        tp3_price=tp3,
        tp4_price=tp4,
        tp1_pct=tp1_pct,
        tp2_pct=tp2_pct,
        tp3_pct=tp3_pct,
        tp4_pct=tp4_pct,
        macro_trend_4h=macro_trend,
        confidence_pct=88,
        candle_timestamp=candle_ts,
    )
    return setup, curr_tl, curr_dir
