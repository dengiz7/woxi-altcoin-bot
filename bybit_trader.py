# -*- coding: utf-8 -*-
"""
Bybit V5 Standart Alt Hesap Demo Trading Otomatik Al-Sat Motoru
- Resmi Bybit V5 Demo API: https://api-demo.bybit.com
- Sadece Python standart kütüphanesi kullanır (sıfır harici bağımlılık).
- Altcoin Bot (WaveTrend 4H): TP1 (%100 Kapanış) ve SL emirlerini Bybit Demo üzerinde otomatik yönetir.
- WOXI-BM (CALMILO 1H/30m): TP1 (%40 + Break-Even), TP2 (%30), TP3 (%20), TP4 (%10) kısmi kapatma ve
  Trailing Stop güncellemelerini gerçek Bybit Demo emirlerine/stop-loss'una uygular.
"""

import hashlib
import hmac
import json
import math
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP
from typing import Dict, List, Optional, Tuple

from config import Config
from strategy_engine import SignalSetup


class BybitDemoTrader:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        enabled: Optional[bool] = None,
    ):
        Config.reload()
        self.api_key = (api_key if api_key is not None else Config.BYBIT_DEMO_API_KEY).strip()
        self.api_secret = (api_secret if api_secret is not None else Config.BYBIT_DEMO_API_SECRET).strip()
        self.base_url = (base_url if base_url is not None else Config.BYBIT_DEMO_BASE_URL).rstrip("/")
        self.enabled: bool = Config.DEMO_AUTO_TRADE_ENABLED if enabled is None else bool(enabled)
        self._ssl_ctx = ssl.create_default_context()
        self._inst_cache: Dict[str, Dict[str, str]] = {}
        self._time_offset_ms: Optional[int] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _get_timestamp_ms(self) -> str:
        """Bybit sunucu saatiyle senkron milisaniye zaman damgası üretir."""
        local_ms = int(time.time() * 1000)
        if self._time_offset_ms is None:
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/v5/market/time",
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5, context=self._ssl_ctx) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    res = data.get("result") or {}
                    srv_nano = res.get("timeNano")
                    srv_sec = res.get("timeSecond")
                    if srv_nano:
                        self._time_offset_ms = int(int(srv_nano) / 1_000_000) - local_ms
                    elif srv_sec:
                        self._time_offset_ms = int(srv_sec) * 1000 - local_ms
                    else:
                        self._time_offset_ms = 0
            except Exception:
                self._time_offset_ms = 0
        return str(local_ms + (self._time_offset_ms or 0))

    def _sign(self, timestamp: str, recv_window: str, payload_str: str) -> str:
        raw = f"{timestamp}{self.api_key}{recv_window}{payload_str}"
        return hmac.new(
            self.api_secret.encode("utf-8"),
            raw.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        signed: bool = True,
        timeout: int = 12,
        _retry_ts: bool = True,
    ) -> Dict:
        url = f"{self.base_url}{path}"
        recv_window = "20000"
        ts = self._get_timestamp_ms()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }

        body_str = ""
        query_str = ""
        m_upper = method.upper()

        if m_upper == "GET":
            if params:
                query_str = urllib.parse.urlencode(params)
                url = f"{url}?{query_str}"
            sign_payload = query_str
        else:
            headers["Content-Type"] = "application/json"
            if params:
                body_str = json.dumps(params)
            sign_payload = body_str

        if signed:
            if not self.is_configured:
                return {"retCode": -1, "retMsg": "Bybit Demo API Key veya Secret eksik"}
            headers["X-BAPI-API-KEY"] = self.api_key
            headers["X-BAPI-TIMESTAMP"] = ts
            headers["X-BAPI-RECV-WINDOW"] = recv_window
            headers["X-BAPI-SIGN"] = self._sign(ts, recv_window, sign_payload)

        req_data = body_str.encode("utf-8") if (m_upper != "GET" and body_str) else None
        req = urllib.request.Request(url, data=req_data, headers=headers, method=m_upper)

        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self._ssl_ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(err_body)
            except Exception:
                return {"retCode": he.code, "retMsg": f"HTTP {he.code}: {err_body}"}
        except Exception as exc:
            return {"retCode": -999, "retMsg": str(exc)}

        if signed and _retry_ts and data.get("retCode") == 10002:
            self._time_offset_ms = None
            return self._request(method, path, params=params, signed=signed, timeout=timeout, _retry_ts=False)
        return data

    def get_instrument_spec(self, symbol: str) -> Dict[str, str]:
        """Paritenin lot adımı, tick adımı ve kaldıraç sınırlarını çeker."""
        if symbol in self._inst_cache:
            return self._inst_cache[symbol]

        res = self._request(
            "GET",
            "/v5/market/instruments-info",
            {"category": "linear", "symbol": symbol},
            signed=False,
        )
        spec = {
            "tickSize": "0.0001",
            "qtyStep": "0.01",
            "minOrderQty": "0.01",
            "minNotionalValue": "5",
            "maxLeverage": "25",
        }
        if res.get("retCode") == 0:
            lst = (res.get("result") or {}).get("list") or []
            if lst:
                inst = lst[0]
                pf = inst.get("priceFilter") or {}
                lf = inst.get("lotSizeFilter") or {}
                lv = inst.get("leverageFilter") or {}
                spec["tickSize"] = str(pf.get("tickSize") or "0.0001")
                spec["qtyStep"] = str(lf.get("qtyStep") or "0.01")
                spec["minOrderQty"] = str(lf.get("minOrderQty") or "0.01")
                spec["minNotionalValue"] = str(lf.get("minNotionalValue") or "5")
                spec["maxLeverage"] = str(lv.get("maxLeverage") or "25")
                self._inst_cache[symbol] = spec
        return spec

    @staticmethod
    def round_step(val: object, step_str: str, round_down: bool = True, round_up: bool = False) -> str:
        try:
            d_val = val if isinstance(val, Decimal) else Decimal(str(val))
            d_step = Decimal(str(step_str))
            if d_step <= 0:
                return f"{val:.4f}"
            if round_up:
                mode = ROUND_UP
            elif round_down:
                mode = ROUND_DOWN
            else:
                mode = ROUND_HALF_UP
            rounded = (d_val / d_step).quantize(Decimal("1"), rounding=mode) * d_step
            dp = max(0, -d_step.normalize().as_tuple().exponent)
            return f"{rounded:.{dp}f}"
        except Exception:
            return f"{val:.4f}"

    def get_demo_account_summary(self) -> Optional[Dict[str, float]]:
        """Bybit Demo UNIFIED cüzdan bakiyesi, net equity ve açık PnL bilgisini döner."""
        if not self.is_configured:
            return None
        res = self._request("GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"}, signed=True)
        if res.get("retCode") != 0:
            return None
        lst = (res.get("result") or {}).get("list") or []
        if not lst:
            return None
        acc = lst[0]
        for coin_info in acc.get("coin") or []:
            if coin_info.get("coin") == "USDT":
                try:
                    wb = float(coin_info.get("walletBalance") or 0.0)
                    eq = float(coin_info.get("equity") or wb)
                    upnl = float(coin_info.get("unrealisedPnl") or (eq - wb))
                    return {
                        "wallet_balance": round(wb, 2),
                        "total_equity": round(eq, 2),
                        "unrealised_pnl": round(upnl, 2),
                    }
                except Exception:
                    break
        try:
            wb = float(acc.get("totalWalletBalance") or 0.0)
            eq = float(acc.get("totalEquity") or wb)
            upnl = float(acc.get("totalPerpUPL") or (eq - wb))
            return {
                "wallet_balance": round(wb, 2),
                "total_equity": round(eq, 2),
                "unrealised_pnl": round(upnl, 2),
            }
        except Exception:
            return None

    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        if not self.is_configured:
            return []
        params: Dict[str, str] = {"category": "linear", "settleCoin": "USDT"}
        if symbol:
            params["symbol"] = symbol
        res = self._request("GET", "/v5/position/list", params, signed=True)
        if res.get("retCode") != 0:
            return []
        raw_list = (res.get("result") or {}).get("list") or []
        open_pos: List[Dict] = []
        for p in raw_list:
            try:
                if float(p.get("size") or 0.0) > 0:
                    open_pos.append(p)
            except Exception:
                continue
        return open_pos

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        if not self.is_configured:
            return []
        params: Dict[str, str] = {"category": "linear", "settleCoin": "USDT"}
        if symbol:
            params["symbol"] = symbol
        res = self._request("GET", "/v5/order/realtime", params, signed=True)
        if res.get("retCode") != 0:
            return []
        return (res.get("result") or {}).get("list") or []

    def get_closed_pnl_records(
        self,
        symbol: Optional[str] = None,
        start_time_ms: Optional[int] = None,
        limit: int = 30,
    ) -> List[Dict]:
        if not self.is_configured:
            return []
        params: Dict[str, str] = {"category": "linear", "limit": str(limit)}
        if symbol:
            params["symbol"] = symbol
        if start_time_ms is not None and start_time_ms > 0:
            params["startTime"] = str(start_time_ms)
        res = self._request("GET", "/v5/position/closed-pnl", params, signed=True)
        if res.get("retCode") != 0:
            return []
        return (res.get("result") or {}).get("list") or []

    def ensure_leverage(self, symbol: str, leverage: int = Config.DEFAULT_LEVERAGE) -> int:
        spec = self.get_instrument_spec(symbol)
        try:
            max_lev = int(float(spec.get("maxLeverage", "25")))
        except Exception:
            max_lev = 25
        eff_lev = max(1, min(int(leverage), max_lev))
        lev_str = str(eff_lev)

        self._request(
            "POST",
            "/v5/position/switch-isolated",
            {
                "category": "linear",
                "symbol": symbol,
                "tradeMode": 1,  # 1: Isolated, 0: Cross
                "buyLeverage": lev_str,
                "sellLeverage": lev_str,
            },
            signed=True,
        )
        self._request(
            "POST",
            "/v5/position/set-leverage",
            {
                "category": "linear",
                "symbol": symbol,
                "buyLeverage": lev_str,
                "sellLeverage": lev_str,
            },
            signed=True,
        )
        return eff_lev

    def _create_order_with_pos_idx(self, order_params: Dict, direction: str) -> Tuple[Dict, int]:
        """Tek Yönlü (0) modda emir gönderir; hesap Hedge moddaysa (1/2) otomatik uyarlar."""
        pos_idx = int(order_params.get("positionIdx", 0))
        payload = dict(order_params)
        payload["positionIdx"] = pos_idx
        res = self._request("POST", "/v5/order/create", payload, signed=True)
        if res.get("retCode") == 10001 and "position idx" in str(res.get("retMsg", "")).lower():
            alt_idx = 1 if direction == "LONG" else 2
            if alt_idx != pos_idx:
                payload["positionIdx"] = alt_idx
                res = self._request("POST", "/v5/order/create", payload, signed=True)
                pos_idx = alt_idx
        return res, pos_idx

    def cancel_all_symbol_orders(self, symbol: str) -> None:
        if not self.is_configured:
            return
        self._request(
            "POST",
            "/v5/order/cancel-all",
            {"category": "linear", "symbol": symbol},
            signed=True,
        )

    def cancel_all_open_orders(self) -> int:
        if not self.is_configured:
            return 0
        open_ords = self.get_open_orders()
        symbols = {o.get("symbol") for o in open_ords if o.get("symbol")}
        cancelled = 0
        for sym in symbols:
            res = self._request(
                "POST",
                "/v5/order/cancel-all",
                {"category": "linear", "symbol": sym},
                signed=True,
            )
            if res.get("retCode") == 0:
                cancelled += 1
        return cancelled

    def close_all_open_positions(self) -> int:
        if not self.is_configured:
            return 0
        open_pos = self.get_open_positions()
        closed_cnt = 0
        for p in open_pos:
            sym = p.get("symbol")
            side = p.get("side")
            sz = p.get("size")
            if not sym or not sz or float(sz) <= 0:
                continue
            close_side = "Sell" if side == "Buy" else "Buy"
            pos_idx = int(p.get("positionIdx") or 0)
            res = self._request(
                "POST",
                "/v5/order/create",
                {
                    "category": "linear",
                    "symbol": sym,
                    "side": close_side,
                    "orderType": "Market",
                    "qty": str(sz),
                    "reduceOnly": True,
                    "positionIdx": pos_idx,
                },
                signed=True,
            )
            if res.get("retCode") == 0:
                closed_cnt += 1
        return closed_cnt

    def reset_demo_account(self, target_usd: float = 100.0) -> Tuple[int, int, float, str]:
        """
        1) Tüm açık Demo pozisyonları kapatır,
        2) Bekleyen tüm emirleri iptal eder,
        3) /v5/account/demo-apply-money ile gerçek Demo USDT bakiyesini hedef tutara eşitler.
        """
        if not self.is_configured:
            return 0, 0, target_usd, "API anahtarı tanımlı değil"

        closed_pos = self.close_all_open_positions()
        cancelled_ords = self.cancel_all_open_orders()
        time.sleep(0.8)

        summary = self.get_demo_account_summary()
        if not summary:
            return closed_pos, cancelled_ords, target_usd, "Bybit Demo hesap bakiyesi okunamadı"

        cur_wb = summary["wallet_balance"]
        diff = int(round(target_usd - cur_wb))
        note = ""
        if abs(diff) >= 1:
            adj_type = 0 if diff > 0 else 1
            req_amt = min(abs(diff), 100000)
            res = self._request(
                "POST",
                "/v5/account/demo-apply-money",
                {
                    "adjustType": adj_type,
                    "utaDemoApplyMoney": [
                        {
                            "coin": "USDT",
                            "amountStr": str(req_amt),
                        }
                    ],
                },
                signed=True,
            )
            inner_res = res.get("result") or {}
            if res.get("retCode") != 0 or inner_res.get("orderStatus") == "FAIL":
                err_txt = inner_res.get("retMsg") or res.get("retMsg")
                note = f"Bakiye eşitleme uyarısı: {err_txt}"
            elif abs(diff) > 100000:
                note = "Tek seferde en fazla 100.000 USDT düzenlenebilir; gerekirse 1 dk sonra /kasa komutunu tekrarlayın."
            time.sleep(0.6)
            summary = self.get_demo_account_summary()
            if summary:
                cur_wb = summary["wallet_balance"]
        return closed_pos, cancelled_ords, round(cur_wb, 2), note

    def place_signal_order(
        self,
        setup: SignalSetup,
        trade: Dict,
        virtual_bankroll_usd: float,
    ) -> Tuple[bool, Optional[Dict], str]:
        """
        Sinyal oluştuğunda Bybit Demo Alt Hesapta %10 marjin ve 10x (veya parite limiti)
        izole kaldıraçla Market emir açar ve ilk SL/TP korumasını borsaya yerleştirir.
        """
        if not self.is_configured or not self.enabled:
            return False, None, ""

        symbol = setup.symbol
        direction = setup.direction
        side = "Buy" if direction == "LONG" else "Sell"

        # Aynı sembolde zaten açık demo pozisyon varsa üzerine yazma/çakışma önle
        existing = self.get_open_positions(symbol=symbol)
        if existing:
            return (
                False,
                None,
                f"ℹ️ <b>Bybit Demo:</b> #{symbol} için borsada zaten açık pozisyon olduğundan yeni emir çakışmayı önlemek için atlandı.",
            )

        if Config.MAX_CONCURRENT_DEMO_TRADES > 0:
            all_open = self.get_open_positions()
            if len(all_open) >= Config.MAX_CONCURRENT_DEMO_TRADES:
                return (
                    False,
                    None,
                    f"⚠️ <b>Bybit Demo Kasa Koruması:</b> Maksimum {Config.MAX_CONCURRENT_DEMO_TRADES} açık pozisyon sınırına ulaşıldığı için #{symbol} atlandı.",
                )

        bankroll = max(10.0, float(virtual_bankroll_usd))
        margin_usd = float(trade.get("margin_usd") or round(bankroll * (Config.MARGIN_PER_TRADE_PCT / 100.0), 2))
        margin_usd = max(2.50, margin_usd)

        eff_lev = self.ensure_leverage(symbol, int(trade.get("leverage") or Config.DEFAULT_LEVERAGE))
        notional_usd = margin_usd * eff_lev
        entry_ref = float(setup.entry_price)
        if entry_ref <= 0:
            return False, None, ""

        spec = self.get_instrument_spec(symbol)
        min_qty = float(spec["minOrderQty"])
        min_notional = float(spec["minNotionalValue"])

        raw_qty = notional_usd / entry_ref
        qty_str = self.round_step(raw_qty, spec["qtyStep"], round_down=True)
        if float(qty_str) < min_qty:
            qty_str = self.round_step(min_qty, spec["qtyStep"], round_up=True)
        if float(qty_str) * entry_ref < min_notional:
            needed_qty = (min_notional * 1.03) / entry_ref
            qty_str = self.round_step(max(needed_qty, min_qty), spec["qtyStep"], round_up=True)

        if float(qty_str) <= 0:
            return False, None, f"⚠️ <b>Bybit Demo Hatası:</b> #{symbol} miktarı minimum lotu karşılamadı."

        sl_str = self.round_step(setup.sl_price, spec["tickSize"], round_down=(direction == "LONG"))
        if setup.engine == "ALTCOIN_WT_4H":
            tp_target = setup.tp1_price
            tp_label = f"TP1 (%100 Kapanış): <code>{self.round_step(tp_target, spec['tickSize'], round_down=(direction == 'SHORT'))}</code>"
        else:
            tp_target = setup.tp4_price
            tp_label = (
                f"Kademeler: TP1(%40)→TP4(<code>{self.round_step(tp_target, spec['tickSize'], round_down=(direction == 'SHORT'))}</code>) + Trailing"
            )

        tp_str = self.round_step(tp_target, spec["tickSize"], round_down=(direction == "SHORT"))

        self.cancel_all_symbol_orders(symbol)
        order_params = {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": qty_str,
            "takeProfit": tp_str,
            "stopLoss": sl_str,
            "tpTriggerBy": "LastPrice",
            "slTriggerBy": "LastPrice",
            "positionIdx": 0,
        }
        res, used_pos_idx = self._create_order_with_pos_idx(order_params, direction)
        if res.get("retCode") != 0:
            return False, None, f"⚠️ <b>Bybit Demo Emir Hatası:</b> <code>{res.get('retMsg')}</code>"

        order_id = str((res.get("result") or {}).get("orderId") or "")
        filled_qty = float(qty_str)
        avg_price = entry_ref

        time.sleep(0.25)
        opened_pos = self.get_open_positions(symbol=symbol)
        if opened_pos:
            pos = opened_pos[0]
            try:
                filled_qty = float(pos.get("size") or filled_qty)
                avg_price = float(pos.get("avgPrice") or avg_price)
                used_pos_idx = int(pos.get("positionIdx") or used_pos_idx)
            except Exception:
                pass

        meta = {
            "demo_order_placed": True,
            "demo_order_id": order_id,
            "demo_entry_qty": filled_qty,
            "demo_avg_price": avg_price,
            "demo_leverage": eff_lev,
            "demo_position_idx": used_pos_idx,
            "demo_opened_at_ms": int(time.time() * 1000),
        }
        note = (
            f"🤖 <b>BYBIT DEMO ALT HESAP İŞLEMİ AÇILDI!</b>\n"
            f"  • <b>Emir:</b> <code>{side} Market</code> | <b>Miktar:</b> <code>{filled_qty}</code> @ <code>{avg_price}</code>\n"
            f"  • <b>Kaldıraç / Marjin:</b> <code>{eff_lev}x İzole</code> | <code>~{margin_usd:.2f}$</code>\n"
            f"  • <b>Borsa SL:</b> <code>{sl_str}</code> | <b>{tp_label}</b>"
        )
        return True, meta, note

    def update_stop_loss(
        self,
        symbol: str,
        direction: str,
        new_sl: float,
        position_idx: int = 0,
    ) -> Tuple[bool, str]:
        if not self.is_configured or not self.enabled or new_sl <= 0:
            return False, ""
        open_pos = self.get_open_positions(symbol=symbol)
        if not open_pos:
            return False, ""
        pos_idx = int(open_pos[0].get("positionIdx") or position_idx)
        spec = self.get_instrument_spec(symbol)
        sl_str = self.round_step(new_sl, spec["tickSize"], round_down=(direction == "LONG"))
        res = self._request(
            "POST",
            "/v5/position/trading-stop",
            {
                "category": "linear",
                "symbol": symbol,
                "stopLoss": sl_str,
                "slTriggerBy": "LastPrice",
                "positionIdx": pos_idx,
            },
            signed=True,
        )
        rc = res.get("retCode")
        if rc in (0, 34040):
            return True, f"🛡 <b>Bybit Demo SL Güncellendi:</b> <code>{sl_str}</code>"
        return False, f"⚠️ <b>Bybit Demo SL Güncellenemedi:</b> <code>{res.get('retMsg')}</code>"

    def handle_trade_event(self, ev: Dict) -> str:
        """
        Simülatörde üretilen TP1..TP4, BE/Trailing Stop güncellemesi veya SL/Protected Exit olayını
        gerçek Bybit Demo Alt Hesap pozisyonuna uygular.
        """
        if not self.is_configured or not self.enabled or not ev.get("demo_order_placed"):
            return ""

        etype = ev.get("event_type", "")
        symbol = ev.get("symbol", "")
        direction = ev.get("direction", "")
        pos_idx = int(ev.get("demo_position_idx") or 0)
        close_side = "Sell" if direction == "LONG" else "Buy"

        if etype in ("WOXI_BE_UPDATE", "WOXI_TRAIL_UPDATE"):
            _, note = self.update_stop_loss(symbol, direction, float(ev["exit_price"]), position_idx=pos_idx)
            return note

        open_pos = self.get_open_positions(symbol=symbol)
        if not open_pos:
            self.cancel_all_symbol_orders(symbol)
            return "ℹ️ <i>Bybit Demo: Pozisyon borsadaki TP/SL ile zaten kapanmış.</i>"

        pos = open_pos[0]
        cur_size = float(pos.get("size") or 0.0)
        pos_idx = int(pos.get("positionIdx") or pos_idx)
        if cur_size <= 0:
            self.cancel_all_symbol_orders(symbol)
            return ""

        spec = self.get_instrument_spec(symbol)
        min_qty = float(spec["minOrderQty"])

        if etype in ("WOXI_TP1", "WOXI_TP2", "WOXI_TP3"):
            d_cur = Decimal(str(pos.get("size") or cur_size))
            d_orig = Decimal(str(ev.get("demo_entry_qty") or d_cur))
            d_rem_after = Decimal(str(ev.get("remaining_fraction_after", 0.0)))
            d_desired_close = max(Decimal("0"), d_cur - (d_orig * d_rem_after))
            close_qty_str = self.round_step(d_desired_close, spec["qtyStep"], round_down=True)

            if float(close_qty_str) < min_qty:
                return (
                    f"ℹ️ <b>Bybit Demo:</b> Kalan miktar minimum lot (<code>{min_qty}</code>) seviyesinde "
                    f"olduğu için kısmi kapatma yapılamadı; pozisyon SL/Trail korumasıyla sürdürülüyor."
                )

            if float(close_qty_str) > cur_size:
                close_qty_str = self.round_step(cur_size, spec["qtyStep"], round_down=True)

            res, _ = self._create_order_with_pos_idx(
                {
                    "category": "linear",
                    "symbol": symbol,
                    "side": close_side,
                    "orderType": "Market",
                    "qty": close_qty_str,
                    "reduceOnly": True,
                    "positionIdx": pos_idx,
                },
                direction,
            )
            if res.get("retCode") == 0:
                closed_pct = int(round(float(ev.get("close_fraction_pct", 0))))
                return f"🤖 <b>Bybit Demo:</b> #{symbol} %{closed_pct} kısmi kapatıldı (<code>{close_qty_str}</code>)."
            return f"⚠️ <b>Bybit Demo Kısmi Kapatma Hatası:</b> <code>{res.get('retMsg')}</code>"

        if etype in ("ALT_TP1_FULL", "WOXI_TP4", "ALT_SL", "WOXI_SL", "WOXI_PROTECTED_EXIT"):
            close_qty_str = self.round_step(cur_size, spec["qtyStep"], round_down=True)
            if float(close_qty_str) < min_qty:
                close_qty_str = str(cur_size)

            res, _ = self._create_order_with_pos_idx(
                {
                    "category": "linear",
                    "symbol": symbol,
                    "side": close_side,
                    "orderType": "Market",
                    "qty": close_qty_str,
                    "reduceOnly": True,
                    "positionIdx": pos_idx,
                },
                direction,
            )
            self.cancel_all_symbol_orders(symbol)
            if res.get("retCode") == 0:
                return f"🤖 <b>Bybit Demo:</b> #{symbol} kalan pozisyon kapatıldı (<code>{close_qty_str}</code>)."
            return f"⚠️ <b>Bybit Demo Kapatma Hatası:</b> <code>{res.get('retMsg')}</code>"

        return ""

    def format_demo_status_text(self, virtual_bankroll_usd: float) -> str:
        if not self.is_configured:
            return (
                "🤖 <b>BYBIT DEMO ALT HESAP DURUMU</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "⚠️ <b>Durum:</b> Henüz Alt Hesap Demo API Anahtarı bağlanmadı.\n\n"
                "📌 <b>Bağlamak İçin:</b>\n"
                "Bybit'te yeni bir <b>Standart Alt Hesap</b> açıp <i>Demo Trading</i> moduna geçin; "
                "ürettiğiniz <code>BYBIT_DEMO_API_KEY</code> ve <code>BYBIT_DEMO_API_SECRET</code> "
                "değerlerini yerel <code>.env</code> dosyasına veya Render <code>Environment</code> bölümüne ekleyin."
            )

        acc = self.get_demo_account_summary()
        open_pos = self.get_open_positions()
        if acc is not None:
            wb = acc["wallet_balance"]
            eq = acc["total_equity"]
            upnl = acc["unrealised_pnl"]
            wallet_line = (
                f"<b><code>{eq:.2f}$</code></b> "
                f"(Cüzdan: <code>{wb:.2f}$</code> | Açık PnL: <code>{upnl:+.2f}$</code>)"
            )
        else:
            wallet_line = f"<code>{virtual_bankroll_usd:.2f}$</code> <i>(API yanıtı alınamadı)</i>"

        mode_str = "🟢 AKTİF (Sinyallerde Otomatik Açıyor)" if self.enabled else "⏸ DURAKLATILDI (/oto_ac ile başlat)"

        pos_lines: List[str] = []
        for p in open_pos[:25]:
            sym = p.get("symbol")
            side = "🟢 LONG" if p.get("side") == "Buy" else "🔴 SHORT"
            sz = p.get("size")
            avg_p = p.get("avgPrice")
            upnl = float(p.get("unrealisedPnl") or 0.0)
            tp_p = p.get("takeProfit") or "Yok"
            sl_p = p.get("stopLoss") or "Yok"
            pos_lines.append(
                f"  • <b>#{sym}</b> ({side}) | Miktar: <code>{sz}</code> | Giriş: <code>{avg_p}</code> | "
                f"TP/SL: <code>{tp_p} / {sl_p}</code> | PnL: <b><code>{upnl:+.2f}$</code></b>"
            )
        if not pos_lines:
            pos_lines.append("  • <i>Şu an borsada açık Demo pozisyon bulunmuyor.</i>")

        return (
            f"🤖 <b>BYBIT STANDART ALT HESAP DEMO DURUMU</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ <b>Otomatik İşlem:</b> {mode_str}\n"
            f"🏦 <b>Demo Cüzdan / Equity:</b> {wallet_line}\n"
            f"⚡ <b>Kaldıraç &amp; Marjin:</b> {Config.DEFAULT_LEVERAGE}x İzole | Kasanın %{Config.MARGIN_PER_TRADE_PCT:.0f}'u\n"
            f"🛡 <b>Maks. Eşzamanlı İşlem:</b> {Config.MAX_CONCURRENT_DEMO_TRADES}\n\n"
            f"📈 <b>AÇIK DEMO POZİSYONLAR ({len(open_pos)}):</b>\n"
            + "\n".join(pos_lines)
        )
