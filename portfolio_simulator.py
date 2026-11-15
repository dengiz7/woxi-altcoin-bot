# -*- coding: utf-8 -*-
"""
$100 Kasa Simülatörü ve Çok Aşamalı Pozisyon Yöneticisi
- Gerçek borsada emir açmaz; sinyalleri %10 Sabit Bakiye Marjin + 10x İzole Kaldıraç ile canlı takip eder.
- Altcoin Bot (4H WaveTrend): TP1 (+%1.0) vurulduğunda pozisyonun %100'ünü kapatır.
- WOXI-BM (CALMILO): TP1 (%40 + Break-Even), TP2 (%30), TP3 (%20), TP4 (%10) + Trailing Stop yönetir.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import Config, STATE_PATH
from strategy_engine import SignalSetup

TR_TZ = timezone(timedelta(hours=3))


def now_tr() -> datetime:
    return datetime.now(TR_TZ)


class PortfolioSimulator:
    def __init__(self, state_path: Path = STATE_PATH):
        self.state_path = state_path
        self.state: Dict = self._default_state()
        self.load()

    def _default_state(self, bankroll: float = Config.DEFAULT_BANKROLL_USD) -> Dict:
        now = now_tr()
        return {
            "initial_bankroll": round(bankroll, 2),
            "current_bankroll": round(bankroll, 2),
            "day_label": now.strftime("%Y-%m-%d"),
            "day_start_bankroll": round(bankroll, 2),
            "hour_label": now.strftime("%Y-%m-%d %H:00"),
            "hour_start_bankroll": round(bankroll, 2),
            "active_trades": {},
            "events": [],
            "seen_candle_signals": {},
            "total_trades_opened": 0,
            "total_trades_closed": 0,
            "last_scan_time": "",
            "demo_synced": False,
            "demo_wallet_balance": None,
            "demo_total_equity": None,
            "demo_unrealised_pnl": None,
        }

    def load(self) -> None:
        if not self.state_path.exists():
            self.save()
            return
        try:
            raw = self.state_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict) and "current_bankroll" in data:
                self.state.update(data)
        except Exception as exc:
            print(f"[UYARI] state.json okunamadı, varsayılan kullanılıyor: {exc}")

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def reset_bankroll(self, amount: float = Config.DEFAULT_BANKROLL_USD) -> None:
        self.state = self._default_state(max(10.0, float(amount)))
        self.save()

    @property
    def bankroll(self) -> float:
        return float(self.state.get("current_bankroll", Config.DEFAULT_BANKROLL_USD))

    @property
    def active_trades(self) -> Dict[str, Dict]:
        return self.state.setdefault("active_trades", {})

    def is_duplicate_signal(self, setup: SignalSetup) -> bool:
        key = f"{setup.engine}:{setup.symbol}:{setup.timeframe}"
        last_ts = int(self.state.get("seen_candle_signals", {}).get(key, 0))
        if last_ts >= setup.candle_timestamp:
            return True
        # Aynı coinde aynı motordan halihazırda açık işlem varsa tekrar açma
        for tr in self.active_trades.values():
            if tr.get("symbol") == setup.symbol and tr.get("engine") == setup.engine:
                return True
        return False

    def has_opposite_or_same_open(self, symbol: str, direction: str) -> bool:
        for tr in self.active_trades.values():
            if tr.get("symbol") == symbol and tr.get("direction") == direction:
                return True
        return False

    def mark_candle_seen(self, setup: SignalSetup) -> None:
        key = f"{setup.engine}:{setup.symbol}:{setup.timeframe}"
        self.state.setdefault("seen_candle_signals", {})[key] = int(setup.candle_timestamp)

    def open_trade(
        self,
        setup: SignalSetup,
        opened_at: Optional[datetime] = None,
        telegram_msg_id: Optional[int] = None,
    ) -> Dict:
        now = opened_at or now_tr()
        bankroll = max(10.0, self.bankroll)
        margin_usd = round(bankroll * (Config.MARGIN_PER_TRADE_PCT / 100.0), 2)
        leverage = Config.DEFAULT_LEVERAGE
        notional_usd = round(margin_usd * leverage, 2)

        trade = {
            "uid": setup.uid,
            "engine": setup.engine,
            "symbol": setup.symbol,
            "timeframe": setup.timeframe,
            "direction": setup.direction,
            "entry_price": setup.entry_price,
            "initial_sl": setup.sl_price,
            "current_sl": setup.sl_price,
            "sl_pct": setup.sl_pct,
            "sl_reason": "Initial Stop",
            "trend_line": setup.trend_line,
            "tp1_price": setup.tp1_price,
            "tp2_price": setup.tp2_price,
            "tp3_price": setup.tp3_price,
            "tp4_price": setup.tp4_price,
            "tp1_pct": setup.tp1_pct,
            "tp2_pct": setup.tp2_pct,
            "tp3_pct": setup.tp3_pct,
            "tp4_pct": setup.tp4_pct,
            "tp1_hit": False,
            "tp2_hit": False,
            "tp3_hit": False,
            "tp4_hit": False,
            "remaining_fraction": 1.0,
            "margin_usd": margin_usd,
            "leverage": leverage,
            "notional_usd": notional_usd,
            "realized_pnl_usd": 0.0,
            "macro_trend_4h": setup.macro_trend_4h,
            "wt_value": setup.wt_value,
            "is_divergence": setup.is_divergence,
            "is_vip_double": setup.is_vip_double,
            "opened_at": now.isoformat(),
            "telegram_msg_id": telegram_msg_id,
        }
        self.active_trades[setup.uid] = trade
        self.mark_candle_seen(setup)
        self.state["total_trades_opened"] = int(self.state.get("total_trades_opened", 0)) + 1
        self.save()
        return trade

    def set_telegram_msg_id(self, uid: str, msg_id: Optional[int]) -> None:
        if msg_id and uid in self.active_trades:
            self.active_trades[uid]["telegram_msg_id"] = msg_id
            self.save()

    def _record_event(
        self,
        trade: Dict,
        event_type: str,
        exit_price: float,
        close_fraction: float,
        raw_move_pct: float,
        pnl_usd: float,
        ts: datetime,
        extra_note: str = "",
    ) -> Dict:
        lev = float(trade["leverage"])
        net_move_pct = raw_move_pct - (Config.ROUND_TRIP_FEE_PCT if close_fraction > 0 else 0.0)
        ev = {
            "timestamp": ts.isoformat(),
            "time_str": ts.strftime("%H:%M"),
            "date_str": ts.strftime("%Y-%m-%d"),
            "hour_str": ts.strftime("%Y-%m-%d %H:00"),
            "uid": trade["uid"],
            "engine": trade["engine"],
            "symbol": trade["symbol"],
            "timeframe": trade["timeframe"],
            "direction": trade["direction"],
            "entry_price": trade["entry_price"],
            "exit_price": exit_price,
            "event_type": event_type,
            "close_fraction_pct": round(close_fraction * 100.0, 0),
            "spot_pct": round(raw_move_pct, 2),
            "lev_pct": round(net_move_pct * lev, 2),
            "pnl_usd": round(pnl_usd, 4),
            "total_trade_pnl_usd": round(float(trade["realized_pnl_usd"]), 4),
            "bankroll_after": round(self.bankroll, 2),
            "initial_bankroll": float(self.state.get("initial_bankroll", Config.DEFAULT_BANKROLL_USD)),
            "leverage": int(lev),
            "margin_usd": float(trade["margin_usd"]),
            "telegram_msg_id": trade.get("telegram_msg_id"),
            "extra_note": extra_note,
            "remaining_fraction_after": round(float(trade.get("remaining_fraction", 0.0)), 4),
            "demo_order_placed": bool(trade.get("demo_order_placed", False)),
            "demo_entry_qty": float(trade.get("demo_entry_qty") or 0.0),
            "demo_position_idx": int(trade.get("demo_position_idx") or 0),
        }
        self.state.setdefault("events", []).append(ev)
        # Bellek şişmesini önlemek için son 1000 olayı tut
        if len(self.state["events"]) > 1000:
            self.state["events"] = self.state["events"][-1000:]
        return ev

    def _apply_pnl(self, trade: Dict, close_fraction: float, exit_price: float, is_win: bool) -> float:
        entry = float(trade["entry_price"])
        direction = trade["direction"]
        if direction == "LONG":
            raw_pct = (exit_price - entry) / entry * 100.0
        else:
            raw_pct = (entry - exit_price) / entry * 100.0

        net_pct = raw_pct - Config.ROUND_TRIP_FEE_PCT
        notional_closed = float(trade["notional_usd"]) * close_fraction
        pnl = notional_closed * (net_pct / 100.0)
        # İzole marjin koruması: tek işlem zararı yatırılan marjini aşamaz
        max_loss = -float(trade["margin_usd"]) * close_fraction
        if pnl < max_loss:
            pnl = max_loss

        self.state["current_bankroll"] = round(max(0.0, self.bankroll + pnl), 2)
        trade["realized_pnl_usd"] = round(float(trade["realized_pnl_usd"]) + pnl, 4)
        trade["remaining_fraction"] = round(max(0.0, float(trade["remaining_fraction"]) - close_fraction), 4)
        return pnl

    def update_active_trades(
        self,
        live_prices: Dict[str, float],
        trailing_lines: Optional[Dict[str, Tuple[float, int]]] = None,
        now: Optional[datetime] = None,
    ) -> List[Dict]:
        """
        Açık pozisyonları güncel fiyatlarla ve CALMILO trend çizgileriyle günceller.
        Oluşan tüm olayları (TP, SL, Trailing Stop, Protected Exit) liste olarak döner.
        """
        ts = now or now_tr()
        trailing_lines = trailing_lines or {}
        emitted: List[Dict] = []
        closed_uids: List[str] = []

        for uid, trade in list(self.active_trades.items()):
            sym = trade["symbol"]
            price = live_prices.get(sym)
            if not price or price <= 0:
                continue

            is_long = trade["direction"] == "LONG"
            entry = float(trade["entry_price"])
            engine = trade["engine"]

            if engine == "ALTCOIN_WT_4H":
                tp1 = float(trade["tp1_price"])
                sl = float(trade["current_sl"])
                hit_tp1 = (price >= tp1) if is_long else (price <= tp1)
                hit_sl = (price <= sl) if is_long else (price >= sl)

                if hit_tp1:
                    frac = float(trade["remaining_fraction"])
                    pnl = self._apply_pnl(trade, frac, tp1, True)
                    raw_pct = abs(tp1 - entry) / entry * 100.0
                    emitted.append(self._record_event(trade, "ALT_TP1_FULL", tp1, frac, raw_pct, pnl, ts))
                    closed_uids.append(uid)
                elif hit_sl:
                    frac = float(trade["remaining_fraction"])
                    pnl = self._apply_pnl(trade, frac, sl, False)
                    raw_pct = -abs(sl - entry) / entry * 100.0
                    emitted.append(self._record_event(trade, "ALT_SL", sl, frac, raw_pct, pnl, ts))
                    closed_uids.append(uid)

            elif engine == "WOXI_CALMILO":
                # 1) Önce hedefleri kontrol et (TP1 -> TP2 -> TP3 -> TP4)
                tp_steps = [
                    ("tp1_hit", "tp1_price", 0.40, "WOXI_TP1"),
                    ("tp2_hit", "tp2_price", 0.30, "WOXI_TP2"),
                    ("tp3_hit", "tp3_price", 0.20, "WOXI_TP3"),
                    ("tp4_hit", "tp4_price", 0.10, "WOXI_TP4"),
                ]
                for flag_key, price_key, frac_target, ev_name in tp_steps:
                    if trade.get(flag_key):
                        continue
                    target_p = float(trade[price_key])
                    reached = (price >= target_p) if is_long else (price <= target_p)
                    if not reached:
                        break
                    frac = min(frac_target, float(trade["remaining_fraction"]))
                    if frac <= 0:
                        break
                    trade[flag_key] = True
                    pnl = self._apply_pnl(trade, frac, target_p, True)
                    raw_pct = abs(target_p - entry) / entry * 100.0
                    emitted.append(self._record_event(trade, ev_name, target_p, frac, raw_pct, pnl, ts))

                    if flag_key == "tp1_hit":
                        # TP1'de stopu giriş seviyesine (Break-Even) çek
                        curr_sl = float(trade["current_sl"])
                        better_be = (entry > curr_sl) if is_long else (entry < curr_sl)
                        if better_be:
                            trade["current_sl"] = entry
                            trade["sl_reason"] = "Break-Even (TP1)"
                            emitted.append(
                                self._record_event(
                                    trade, "WOXI_BE_UPDATE", entry, 0.0, 0.0, 0.0, ts,
                                    extra_note="Break-Even (TP1)",
                                )
                            )
                    if trade["remaining_fraction"] <= 0.001 or flag_key == "tp4_hit":
                        closed_uids.append(uid)
                        break

                if uid in closed_uids:
                    continue

                # 2) Trailing Stop (CALMILO:Trend Line ilerlemişse stopu sıkılaştır)
                tl_key = f"{sym}:{trade['timeframe']}"
                if tl_key in trailing_lines:
                    new_tl, st_dir = trailing_lines[tl_key]
                    expected_dir = 1 if is_long else -1
                    if st_dir == expected_dir and new_tl > 0:
                        curr_sl = float(trade["current_sl"])
                        improves = (new_tl > curr_sl * 1.0015) if is_long else (new_tl < curr_sl * 0.9985)
                        safe_from_spot = (new_tl < price * 0.998) if is_long else (new_tl > price * 1.002)
                        if improves and safe_from_spot:
                            trade["current_sl"] = new_tl
                            trade["sl_reason"] = "Trailing Stop"
                            emitted.append(
                                self._record_event(
                                    trade, "WOXI_TRAIL_UPDATE", new_tl, 0.0, 0.0, 0.0, ts,
                                    extra_note="Trailing Stop",
                                )
                            )

                # 3) Stop-Loss veya Korumalı Çıkış (Protected Exit) kontrolü
                curr_sl = float(trade["current_sl"])
                hit_sl = (price <= curr_sl) if is_long else (price >= curr_sl)
                if hit_sl:
                    frac = float(trade["remaining_fraction"])
                    if frac > 0:
                        raw_pct = ((curr_sl - entry) / entry * 100.0) if is_long else ((entry - curr_sl) / entry * 100.0)
                        pnl = self._apply_pnl(trade, frac, curr_sl, trade.get("tp1_hit", False))
                        ev_name = "WOXI_PROTECTED_EXIT" if trade.get("tp1_hit") else "WOXI_SL"
                        emitted.append(self._record_event(trade, ev_name, curr_sl, frac, raw_pct, pnl, ts))
                    closed_uids.append(uid)

            elif engine == "DEMO_RECOVERED":
                # Bulut yeniden başlatması sonrası borsadan kurtarılan pozisyon Bybit TP/SL ile izlenir
                continue

        for uid in closed_uids:
            self.active_trades.pop(uid, None)
            self.state["total_trades_closed"] = int(self.state.get("total_trades_closed", 0)) + 1

        if emitted or closed_uids:
            self.save()
        return emitted

    def check_time_rollovers(self, now: Optional[datetime] = None) -> Tuple[bool, bool, Dict]:
        """
        Saat veya gün değişimi olup olmadığını kontrol eder.
        Döner: (saat_degisti_mi, gun_degisti_mi, rapor_ozet_bilgisi)
        """
        ts = now or now_tr()
        curr_hour = ts.strftime("%Y-%m-%d %H:00")
        curr_day = ts.strftime("%Y-%m-%d")

        prev_hour = self.state.get("hour_label", curr_hour)
        prev_day = self.state.get("day_label", curr_day)

        hour_changed = (curr_hour != prev_hour)
        day_changed = (curr_day != prev_day)

        snapshot = {
            "prev_hour": prev_hour,
            "prev_day": prev_day,
            "hour_start_bankroll": float(self.state.get("hour_start_bankroll", self.bankroll)),
            "day_start_bankroll": float(self.state.get("day_start_bankroll", self.bankroll)),
            "current_bankroll": self.bankroll,
        }

        if hour_changed:
            self.state["hour_label"] = curr_hour
            self.state["hour_start_bankroll"] = self.bankroll
        if day_changed:
            self.state["day_label"] = curr_day
            self.state["day_start_bankroll"] = self.bankroll
        if hour_changed or day_changed:
            self.save()

        return hour_changed, day_changed, snapshot

    def get_period_events(self, date_str: Optional[str] = None, hour_str: Optional[str] = None) -> List[Dict]:
        out = []
        for ev in self.state.get("events", []):
            if date_str and ev.get("date_str") != date_str:
                continue
            if hour_str and ev.get("hour_str") != hour_str:
                continue
            out.append(ev)
        return out

    def calc_unrealized_pnl(self, live_prices: Dict[str, float]) -> float:
        total = 0.0
        for trade in self.active_trades.values():
            p = live_prices.get(trade["symbol"])
            if not p or p <= 0:
                continue
            entry = float(trade["entry_price"])
            rem = float(trade["remaining_fraction"])
            notional_rem = float(trade["notional_usd"]) * rem
            if trade["direction"] == "LONG":
                pct = (p - entry) / entry * 100.0
            else:
                pct = (entry - p) / entry * 100.0
            total += notional_rem * (pct / 100.0)
        return round(total, 2)

    def attach_demo_meta(self, uid: str, meta: Dict) -> None:
        if uid in self.active_trades and isinstance(meta, dict):
            self.active_trades[uid].update(meta)
            self.save()

    def sync_demo_account_summary(self, acc: Optional[Dict[str, float]]) -> None:
        if not acc:
            return
        wb = round(float(acc.get("wallet_balance", self.bankroll)), 2)
        eq = round(float(acc.get("total_equity", wb)), 2)
        upnl = round(float(acc.get("unrealised_pnl", eq - wb)), 2)

        changed = (
            self.state.get("demo_wallet_balance") != wb
            or self.state.get("demo_total_equity") != eq
            or self.state.get("demo_unrealised_pnl") != upnl
            or not self.state.get("demo_synced")
        )

        is_fresh = (
            not self.state.get("demo_synced")
            and int(self.state.get("total_trades_opened", 0)) == 0
            and not self.state.get("events")
        )
        if is_fresh and wb > 0:
            self.state["initial_bankroll"] = wb
            self.state["day_start_bankroll"] = wb
            self.state["hour_start_bankroll"] = wb

        self.state["demo_synced"] = True
        self.state["demo_wallet_balance"] = wb
        self.state["demo_total_equity"] = eq
        self.state["demo_unrealised_pnl"] = upnl
        self.state["current_bankroll"] = wb
        if changed:
            self.save()

    def close_trade_externally(
        self,
        uid: str,
        exit_price: float,
        pnl_usd: float,
        ts: Optional[datetime] = None,
    ) -> Optional[Dict]:
        trade = self.active_trades.pop(uid, None)
        if not trade:
            return None

        now = ts or now_tr()
        rem_frac = float(trade.get("remaining_fraction") or 1.0)
        entry = float(trade.get("entry_price") or exit_price or 1.0)
        is_long = trade.get("direction") == "LONG"
        if entry > 0 and exit_price > 0:
            raw_pct = ((exit_price - entry) / entry * 100.0) if is_long else ((entry - exit_price) / entry * 100.0)
        else:
            raw_pct = 0.0

        self.state["current_bankroll"] = round(max(0.0, self.bankroll + pnl_usd), 2)
        trade["realized_pnl_usd"] = round(float(trade.get("realized_pnl_usd", 0.0)) + pnl_usd, 4)
        trade["remaining_fraction"] = 0.0

        engine = trade.get("engine", "")
        if engine == "ALTCOIN_WT_4H":
            ev_name = "ALT_TP1_FULL" if pnl_usd >= 0 else "ALT_SL"
        elif engine == "WOXI_CALMILO":
            if pnl_usd >= 0:
                ev_name = "WOXI_PROTECTED_EXIT" if trade.get("tp1_hit") else "WOXI_TP4"
            else:
                ev_name = "WOXI_PROTECTED_EXIT" if trade.get("tp1_hit") else "WOXI_SL"
        else:
            ev_name = "DEMO_TP_CLOSE" if pnl_usd >= 0 else "DEMO_SL_CLOSE"

        ev = self._record_event(trade, ev_name, exit_price or entry, rem_frac, raw_pct, pnl_usd, now, extra_note="Bybit Demo Borsa Kapanışı")
        self.state["total_trades_closed"] = int(self.state.get("total_trades_closed", 0)) + 1
        self.save()
        return ev

    def reconcile_recovered_positions(self, open_positions: List[Dict], ts: Optional[datetime] = None) -> int:
        """Bulut yeniden başlatmasında state kaybolduysa Bybit Demo'daki açık pozisyonları takibe alır."""
        now = ts or now_tr()
        known_symbols = {str(tr.get("symbol", "")) for tr in self.active_trades.values()}
        added = 0
        for p in open_positions:
            sym = str(p.get("symbol") or "")
            if not sym or sym in known_symbols:
                continue
            try:
                sz = float(p.get("size") or 0.0)
                avg_p = float(p.get("avgPrice") or 0.0)
                lev = int(float(p.get("leverage") or Config.DEFAULT_LEVERAGE))
            except Exception:
                continue
            if sz <= 0 or avg_p <= 0:
                continue

            direction = "LONG" if p.get("side") == "Buy" else "SHORT"
            notional = round(sz * avg_p, 2)
            margin = float(p.get("positionIM") or 0.0)
            if margin <= 0:
                margin = round(notional / max(1, lev), 2)

            sl_v = float(p.get("stopLoss") or avg_p)
            tp_v = float(p.get("takeProfit") or avg_p)
            uid = f"REC_{sym}_{int(now.timestamp())}"

            self.active_trades[uid] = {
                "uid": uid,
                "engine": "DEMO_RECOVERED",
                "symbol": sym,
                "timeframe": "LIVE",
                "direction": direction,
                "entry_price": avg_p,
                "initial_sl": sl_v,
                "current_sl": sl_v,
                "sl_pct": round(abs(sl_v - avg_p) / avg_p * 100.0, 2) if sl_v > 0 else 0.0,
                "sl_reason": "Borsa Koruması",
                "trend_line": avg_p,
                "tp1_price": tp_v,
                "tp2_price": tp_v,
                "tp3_price": tp_v,
                "tp4_price": tp_v,
                "tp1_pct": 0.0,
                "tp2_pct": 0.0,
                "tp3_pct": 0.0,
                "tp4_pct": 0.0,
                "tp1_hit": False,
                "tp2_hit": False,
                "tp3_hit": False,
                "tp4_hit": False,
                "remaining_fraction": 1.0,
                "margin_usd": round(margin, 2),
                "leverage": lev,
                "notional_usd": notional,
                "realized_pnl_usd": 0.0,
                "macro_trend_4h": "-",
                "wt_value": 0.0,
                "is_divergence": False,
                "is_vip_double": False,
                "opened_at": now.isoformat(),
                "telegram_msg_id": None,
                "demo_order_placed": True,
                "demo_entry_qty": sz,
                "demo_avg_price": avg_p,
                "demo_leverage": lev,
                "demo_position_idx": int(p.get("positionIdx") or 0),
                "demo_opened_at_ms": int(now.timestamp() * 1000) - 60_000,
            }
            known_symbols.add(sym)
            added += 1

        if added:
            self.save()
        return added
