"""True SMC implementation aligning with Pine instructions (1-11).

1. Minor order flow rebuilt with tri-state trend and puHigh/puLow anchors.
2. Major order flow derived from impulse/base reference candles.
3. IDM gate primes idmLow/idmHigh immediately on structure breaks.
4. IDM selects nearest validated/active zone relative to close price.
5. Equality classification uses ATR * eq_threshold tolerance.
6. Internal/external events require cross-through confirmation.
7. Zone lifecycle enforces validate/test/mitigate logic per rule set.
8. FVG detection gains ATR threshold, fill rules, and HTF support.
9. Liquidity levels originate from pivots with active/break tracking.
10. Key levels supply PDH/PDL/MID per spec; OTE stored when enabled.
11. Outputs expose dedicated DataFrames for major/minor/tested zones.
12. Pivot tolerance, major base selection, and minor bounds mirror Pine defaults.
"""

from dataclasses import dataclass, field
try:
    from typing import Literal
except Exception:  # pragma: no cover - Pydroid fallback
    from typing import Any as Literal
from typing import Optional, Dict, Any, List, Tuple

import math
from collections import deque, defaultdict

import pandas as pd
import numpy as np

# =========================================================
# مفاتيح/إعدادات عامة + تيليغرام (اختياري)
# =========================================================
import os, time, requests

API_KEYS = {
    "BINANCE_API_KEY":     "",  # لا يلزم للبيانات العامة
    "BINANCE_API_SECRET":  "",  # لا يلزم للبيانات العامة
    "TELEGRAM_BOT_TOKEN":  "",  # اختياري للإشعارات
    "TELEGRAM_CHAT_ID":    "",  # اختياري للإشعارات
}
def _get_secret(name: str, default: str = "") -> str:
    return (API_KEYS.get(name, "") or os.getenv(name, "") or default).strip()

@dataclass
class ScannerSettings:
    tg_enable: bool = False
    tg_title_prefix: str = "SMC Alert"
    recent_bars: int = 200
    verbose: bool = False
    debug: bool = False
    # تنبيهات
    alert_bos: bool = True
    alert_choch: bool = True
    alert_bos_plus: bool = True
    alert_mss_plus: bool = False
    alert_idm: bool = True
    alert_ob_tested: bool = False
    alert_ob_mitigated: bool = True
    alert_ob_touch_ext: bool = True
    alert_ob_touch_idm: bool = True
    alert_ob_break_ext: bool = True
    alert_ob_break_idm: bool = True

class TelegramNotifier:
    def __init__(self, enabled: bool, prefix: str):
        self.token = _get_secret("TELEGRAM_BOT_TOKEN")
        self.chat_id = _get_secret("TELEGRAM_CHAT_ID")
        self.prefix = prefix
        self.enabled = enabled and bool(self.token and self.chat_id)

    def send(self, text: str):
        if not self.enabled:
            print("[ALERT] " + text)
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            requests.post(url, json={"chat_id": self.chat_id, "text": text}, timeout=10)
        except Exception as e:
            print(f"[TELEGRAM ERROR] {e}\n{text}")

# =========================================================
# SMC Core
# =========================================================

@dataclass
class SMCEvent:
    index: int
    time: pd.Timestamp
    type: Literal[
        "CHOCH",
        "BOS",
        "MSS",
        "BOS+",
        "MSS+",
        "IDM",
        "FVG_BULL",
        "FVG_BEAR",
        "FVG_BREAK_BULL",
        "FVG_BREAK_BEAR",
        "LIQ_HIGH",
        "LIQ_LOW",
        "LIQ_BREAK_HIGH",
        "LIQ_BREAK_LOW",
        "OB_EXT_BULL",
        "OB_EXT_BEAR",
        "OB_IDM_BULL",
        "OB_IDM_BEAR",
        "OB_TOUCH_EXT",
        "OB_TOUCH_IDM",
        "OB_BREAK_EXT",
        "OB_BREAK_IDM",
        "OF_MAJOR_BULL",
        "OF_MAJOR_BEAR",
        "OF_MINOR_BULL",
        "OF_MINOR_BEAR",
        "OB_VALIDATED",
        "OB_INVALIDATED",
        "OB_TESTED",
        "OB_MITIGATED",
    ]
    direction: Literal["bull", "bear", "na"]
    price: float
    meta: Dict[str, Any]


@dataclass
class SMCResult:
    events: List[SMCEvent]
    internal_swings: pd.DataFrame
    external_swings: pd.DataFrame
    order_blocks: pd.DataFrame
    fvgs: pd.DataFrame
    liquidity_levels: pd.DataFrame
    key_levels: Dict[str, float]
    major_zones: Optional[pd.DataFrame] = None
    minor_zones: Optional[pd.DataFrame] = None
    tested_zones: Optional[pd.DataFrame] = None


class SMC:
    """Smart Money Concepts detector with Pine parity features."""

    def __init__(
        self,
        lengSMC: int = 40,
        swingSize: int = 10,
        structure_type: str = "Choch with IDM",
        eq_threshold: float = 0.0,
        atr_len_eq: int = 300,
        ote_hi: float = 0.78,
        ote_lo: float = 0.61,
        enable_fvg: bool = True,
        enable_liquidity: bool = True,
        enable_key_levels: bool = True,
        enable_ote: bool = True,
        enable_ob: bool = True,
        fvg_touch_rule: str = "touch",
        ob_mitig_rule: str = "touch",
        fvg_fill_rule: str = "midpoint",
        fvg_threshold: float = 0.1,
        fvg_htf_multipliers: Optional[List[int]] = None,
        fvg_delete_on_fill: bool = True,
        minor_bounds: str = "wick",
        major_base_mode: str = "last_opposite_body",
        extend_on_break: bool = True,
        major_ext_inside_required: bool = False,
        extend_on_range_cover: bool = True,
        max_bar_history: int = 500,
        len_factor: int = 1,
    ) -> None:
        """Store configuration and reset per-run state holders."""

        self.lengSMC = int(max(2, lengSMC))
        self.swingSize = int(max(1, swingSize))
        self.structure_type = structure_type
        self.eq_threshold = float(eq_threshold)
        self.atr_len_eq = int(max(1, atr_len_eq))
        self.ote_hi = float(ote_hi)
        self.ote_lo = float(ote_lo)
        self.enable_fvg = enable_fvg
        self.enable_liquidity = enable_liquidity
        self.enable_key_levels = enable_key_levels
        self.enable_ote = enable_ote
        self.enable_ob = enable_ob
        self.fvg_touch_rule = fvg_touch_rule
        self.ob_mitig_rule = ob_mitig_rule
        self.fvg_fill_rule = fvg_fill_rule
        self.fvg_threshold = float(fvg_threshold)
        self.fvg_htf_multipliers = list(fvg_htf_multipliers or [])
        self.fvg_delete_on_fill = bool(fvg_delete_on_fill)
        self.minor_bounds = minor_bounds
        self.major_base_mode = major_base_mode
        self.extend_on_break = bool(extend_on_break)
        self.major_ext_inside_required = bool(major_ext_inside_required)
        self.extend_on_range_cover = bool(extend_on_range_cover)
        self.max_bar_history = int(max_bar_history)
        self.len_factor = int(max(1, len_factor))

        self._reset_runtime()

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------
    def _reset_runtime(self) -> None:
        """Clear per-run caches."""

        self.open = self.high = self.low = self.close = self.volume = None
        self.time_index: Optional[pd.Index] = None
        self.length = 0
        self.events: List[SMCEvent] = []
        self.event_keys: Dict[Tuple[str, float, str], int] = {}

        self.int_t_MS = 0
        self.t_MS = 0
        self.isPrevBos = False

        self.internal_pivots: List[Dict[str, Any]] = []
        self.external_pivots: List[Dict[str, Any]] = []

        self.last_internal_high: Optional[Dict[str, Any]] = None
        self.last_internal_low: Optional[Dict[str, Any]] = None
        self.last_external_high: Optional[Dict[str, Any]] = None
        self.last_external_low: Optional[Dict[str, Any]] = None
        self.pending_external_high: Optional[Dict[str, Any]] = None
        self.pending_external_low: Optional[Dict[str, Any]] = None

        self.findIDM = False
        self.idmLow = np.nan
        self.idmHigh = np.nan

        self.zone_objects: List[Dict[str, Any]] = []
        self.major_zone_objects: List[Dict[str, Any]] = []
        self.minor_zone_objects: List[Dict[str, Any]] = []
        self.tested_zones: List[Dict[str, Any]] = []

        self.major_bull: List[Dict[str, Any]] = []
        self.major_bear: List[Dict[str, Any]] = []
        self.minor_bull: List[Dict[str, Any]] = []
        self.minor_bear: List[Dict[str, Any]] = []

        self.liquidity_levels: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self._last_liq_added_idx = -1

        self.fvgs: List[Dict[str, Any]] = []
        self.htf_buffers: Dict[int, deque] = {}
        self.htf_state: Dict[int, Dict[str, Any]] = {}

        self.atr_series: Optional[np.ndarray] = None
        self.eq_threshold_series: Optional[np.ndarray] = None

        self.minor_state = "notrend"
        self.top_ref = np.nan
        self.bot_ref = np.nan
        self.puHigh = np.nan
        self.puLow = np.nan
        self.puHBar = -1
        self.puLBar = -1

        self.key_levels: Dict[str, float] = {"PDH": np.nan, "PDL": np.nan, "MID": np.nan, "OTE_LOW": np.nan, "OTE_HIGH": np.nan}
        self.last_major_high_value = np.nan
        self.last_major_low_value = np.nan
        self.last_major_high_index = -1
        self.last_major_low_index = -1

        # ربط HH/LL الخارجية بالأحداث فقط (running trackers)
        self.run_high_value = -np.inf
        self.run_high_index = -1
        self.run_low_value = np.inf
        self.run_low_index = -1

        # أم-بار تاريخية بسيطة للسويب
        self._mother_high = np.nan
        self._mother_low = np.nan
        self._mother_idx = -1

        self.current_ote: Optional[Tuple[float, float]] = None

        # --- جديد للباتش A: نية تثبيت HH/LL تؤجل حتى IDM ---
        self._pending_fix: Optional[Dict[str, Any]] = None
        self._idm_y: float = float("nan")
        self._idm_lsthl: float = float("nan")
        self._idm_ctx: Optional[Dict[str, Any]] = None
        self._last_ext_event: Optional[Tuple[str, str]] = None
        self._ext_high_stack: List[Dict[str, Any]] = []
        self._ext_low_stack: List[Dict[str, Any]] = []
        self._last_internal_up_level: float = float("nan")
        self._last_internal_down_level: float = float("nan")

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------
    def _record_event(
        self,
        i: int,
        event_type: str,
        direction: str,
        price: float,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append event if unique at (type, price, direction)."""

        key_id: Any = None
        if meta:
            for candidate in ("zone_id", "fvg_id", "level_id", "level"):
                if candidate in meta:
                    key_id = meta[candidate]
                    break
        if key_id is None:
            key_id = round(float(price), 8)
        key = (event_type, direction, key_id)
        if key in self.event_keys:
            return
        self.event_keys[key] = i
        self.events.append(
            SMCEvent(
                index=i,
                time=pd.Timestamp(self.time_index[i]),
                type=event_type,  # type: ignore[arg-type]
                direction=direction,  # type: ignore[arg-type]
                price=float(price),
                meta=meta or {},
            )
        )

    def _atr(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
        """Return ATR series (SMA of true range)."""

        tr = np.zeros_like(close)
        tr[0] = high[0] - low[0]
        for i in range(1, len(close)):
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i - 1])
            lc = abs(low[i] - close[i - 1])
            tr[i] = max(hl, hc, lc)
        atr = pd.Series(tr).rolling(window=period, min_periods=1).mean().to_numpy()
        return atr

    # ------------------------------------------------------------------
    def fit_transform(self, df: pd.DataFrame) -> SMCResult:
        """Execute SMC pipeline over OHLCV DataFrame."""

        if df.empty:
            raise ValueError("DataFrame is empty")

        data = df.copy()
        if "volume" not in data.columns:
            data["volume"] = 1.0

        if not isinstance(data.index, pd.DatetimeIndex):
            data.index = pd.date_range(start=pd.Timestamp.now(), periods=len(data), freq="T")

        self._reset_runtime()

        self.open = data["open"].to_numpy(dtype=float)
        self.high = data["high"].to_numpy(dtype=float)
        self.low = data["low"].to_numpy(dtype=float)
        self.close = data["close"].to_numpy(dtype=float)
        self.volume = data["volume"].to_numpy(dtype=float)
        self.time_index = data.index
        self.length = len(data)

        self.atr_series = self._atr(self.high, self.low, self.close, self.atr_len_eq)
        self.eq_threshold_series = self.atr_series * self.eq_threshold
        self._daily = (
            pd.DataFrame({"high": self.high, "low": self.low}, index=self.time_index)
            .resample("1D")
            .agg({"high": "max", "low": "min"})
        )

        # Initialize minor references
        if self.length:
            self.top_ref = self.high[0]
            self.bot_ref = self.low[0]
            self.puHigh = self.high[0]
            self.puLow = self.low[0]
            self.puHBar = 0
            self.puLBar = 0
        for mult in self.fvg_htf_multipliers:
            self.htf_buffers[mult] = deque(maxlen=3)
            self.htf_state[mult] = {}

        for i in range(self.length):
            # --- (1) آلة حالة للمينور بدل نافذة pivots ---
            self._update_minor_state_machine(i)

            # --- (2) ربط HH/LL الخارجية بالأحداث فقط: تتبّع جاري لكل بار ---
            if self.high[i] >= self.run_high_value:
                self.run_high_value, self.run_high_index = self.high[i], i
            if self.low[i] <= self.run_low_value:
                self.run_low_value, self.run_low_index = self.low[i], i

            # نافذة الـ external القديمة تبقى موجودة لكن تُعطّل
            self._update_external_swings(i)  # تُبقي التوقيع، والدالة أدناه pass

            # إشارات الهيكل
            self._emit_choch_bos_mss_internal(i)
            self._emit_choch_bos_mss_external(i)

            # --- (3) منشئ سويب ثنائي الجيران + Mother bar للمينور ---
            if self.enable_ob:
                self._update_idm_and_obs(i)
                self._detect_and_create_poi_zones_from_sweep(i)

            if self.enable_fvg:
                self._create_fvg(i)
                self._update_fvg_state(i)
            if self.enable_liquidity:
                self._update_liquidity_levels(i)
            if self.enable_key_levels:
                self._compute_key_levels(i)
            if self.enable_ote:
                self._compute_ote_zone(i)

        internal_df = pd.DataFrame(self.internal_pivots)
        external_df = pd.DataFrame(self.external_pivots)
        order_blocks_df = pd.DataFrame([zone.copy() for zone in self.zone_objects])
        fvgs_df = pd.DataFrame(self.fvgs)
        liq_df = pd.DataFrame(list(self.liquidity_levels.values())) if self.liquidity_levels else pd.DataFrame(columns=["id", "side", "price", "status", "created_index", "created_time", "broken_index", "broken_time"])
        major_df = pd.DataFrame([zone.copy() for zone in self.major_zone_objects])
        minor_df = pd.DataFrame([zone.copy() for zone in self.minor_zone_objects])
        tested_df = pd.DataFrame(self.tested_zones)

        result = SMCResult(
            events=self.events,
            internal_swings=internal_df,
            external_swings=external_df,
            order_blocks=order_blocks_df,
            fvgs=fvgs_df,
            liquidity_levels=liq_df,
            key_levels=self.key_levels.copy(),
            major_zones=major_df if not major_df.empty else None,
            minor_zones=minor_df if not minor_df.empty else None,
            tested_zones=tested_df if not tested_df.empty else None,
        )
        return result

    # ------------------------------------------------------------------
    def _detect_internal_pivots(self, i: int) -> None:
        """DEPRECATED: استُبدلت بآلة الحالة للمينور لضمان تطابق Pine."""
        return

    # آلة حالة للمينور: mnStrc + puHigh/puLow مع تثبيت الانعكاس الداخلي عند تغير الحالة
    def _update_minor_state_machine(self, i: int) -> None:
        hi = self.high[i]
        lo = self.low[i]
        if math.isnan(self.top_ref):
            self.top_ref = hi
        if math.isnan(self.bot_ref):
            self.bot_ref = lo

        # تصنيف Pine:
        if hi >= self.top_ref and lo > self.bot_ref:
            new_state = "uptrend"
        elif hi < self.top_ref and lo <= self.bot_ref:
            new_state = "downtrend"
        else:
            new_state = "notrend"

        if new_state != self.minor_state:
            # تثبيت آخر pu كنقطة انعكاس داخلية
            if new_state == "uptrend" and self.puLBar >= 0 and not math.isnan(self.puLow):
                self.last_internal_low = {
                    "index": int(self.puLBar),
                    "time": self.time_index[int(self.puLBar)],
                    "kind": "low",
                    "value": float(self.puLow),
                    "label": "HL",
                }
                self.internal_pivots.append(self.last_internal_low)
            if new_state == "downtrend" and self.puHBar >= 0 and not math.isnan(self.puHigh):
                self.last_internal_high = {
                    "index": int(self.puHBar),
                    "time": self.time_index[int(self.puHBar)],
                    "kind": "high",
                    "value": float(self.puHigh),
                    "label": "LH",
                }
                self.internal_pivots.append(self.last_internal_high)
            self.minor_state = new_state

        # تحديث المراجع
        if self.minor_state == "uptrend":
            self.top_ref = max(self.top_ref, hi)
            self.bot_ref = lo
        elif self.minor_state == "downtrend":
            self.top_ref = hi
            self.bot_ref = min(self.bot_ref, lo)
        else:
            self.top_ref = max(self.top_ref, hi)
            self.bot_ref = min(self.bot_ref, lo)

        # تحديث pu
        self.puHigh = hi
        self.puLow = lo
        self.puHBar = i
        self.puLBar = i

    # ------------------------------------------------------------------
    def _update_external_swings(self, i: int) -> None:
        """DEPRECATED: الآن تثبيت HH/LL الخارجية يتم فقط عند أحداث BOS+/CHOCH+."""
        return

    def _confirm_external_pivot(self, kind: str) -> Optional[Dict[str, Any]]:
        """Promote pending external pivot once structure break occurs (kept for compatibility)."""
        if kind == "high":
            pivot = self.pending_external_high
            if pivot is None:
                return None
            self.last_external_high = pivot
            self.pending_external_high = None
            self.external_pivots.append(pivot)
            self.last_major_high_value = pivot["value"]
            self.last_major_high_index = pivot["index"]
            return pivot
        pivot = self.pending_external_low
        if pivot is None:
            return None
        self.last_external_low = pivot
        self.pending_external_low = None
        self.external_pivots.append(pivot)
        self.last_major_low_value = pivot["value"]
        self.last_major_low_index = pivot["index"]
        return pivot
    # ------------------------------------------------------------------
    def _emit_choch_bos_mss_internal(self, i: int) -> None:
        """Emit internal BOS/MSS with cross rule."""

        if not self.internal_pivots:
            return

        last_high = self.last_internal_high
        last_low = self.last_internal_low
        tol = float(self.eq_threshold_series[i]) if self.eq_threshold_series is not None else 0.0

        if last_high is not None and last_high["index"] < i:
            level = float(last_high["value"])
            if i > 0 and (self.close[i - 1] < level - tol) and (self.close[i] >= level - tol):
                if math.isfinite(self._last_internal_up_level) and math.isclose(self._last_internal_up_level, level, abs_tol=tol):
                    pass
                else:
                    prev_state = self.int_t_MS
                    event_type = "CHOCH" if prev_state < 0 else "BOS"
                    direction = "bull"
                    meta = {"level": level, "kind": "internal_high", "label": last_high["label"]}
                    self._record_event(i, event_type, direction, level, meta)
                    self.int_t_MS = 1
                    self._last_internal_up_level = level
                    self._last_internal_down_level = float("nan")
                    self._arm_idm(level, "bull")

        if last_low is not None and last_low["index"] < i:
            level = float(last_low["value"])
            if i > 0 and (self.close[i - 1] > level + tol) and (self.close[i] <= level + tol):
                if math.isfinite(self._last_internal_down_level) and math.isclose(self._last_internal_down_level, level, abs_tol=tol):
                    pass
                else:
                    prev_state = self.int_t_MS
                    event_type = "CHOCH" if prev_state > 0 else "BOS"
                    direction = "bear"
                    meta = {"level": level, "kind": "internal_low", "label": last_low["label"]}
                    self._record_event(i, event_type, direction, level, meta)
                    self.int_t_MS = -1
                    self._last_internal_down_level = level
                    self._last_internal_up_level = float("nan")
                    self._arm_idm(level, "bear")

    # ------------------------------------------------------------------
    def _emit_choch_bos_mss_external(self, i: int) -> None:
        """Emit external BOS+/MSS+ with cross rule."""

        last_high = self.last_external_high
        last_low = self.last_external_low
        tol = float(self.eq_threshold_series[i]) if self.eq_threshold_series is not None else 0.0

        # BOS+ / MSS+ — صعود
        if last_high is not None and last_high["index"] < i:
            # استخدم قيمة ومؤشر HL المؤكَّد حصراً كمستوى الكسر
            level = float(last_high["value"])
            ref_index = int(last_high["index"])
            if i > 0 and (self.close[i - 1] < level - tol) and (self.close[i] >= level - tol):
                prev_state = self.t_MS
                event_type = "CHOCH+" if prev_state < 0 else "BOS+"
                direction = "bull"
                meta = {"level": level, "kind": "external_high", "label": last_high["label"]}
                self._record_event(i, event_type, direction, level, meta)
                self.t_MS = 1
                self._last_ext_event = (event_type, direction)
                self.isPrevBos = event_type == "BOS+"

                self._idm_y = float(level)
                self._idm_lsthl = float(self.last_internal_low["value"]) if self.last_internal_low else float("nan")

                # --- باتش A: لا تثبيت HH هنا، فقط نحفظ نية التثبيت حتى IDM ---
                self._pending_fix = {"side": "bull", "price": float(level), "index": ref_index}

                # منشئ Major OB من السويب (يبقى كما هو)
                confirmed = self.last_external_high
                if confirmed is not None:
                    self._create_major_zone_from_sweep(i, "bull", confirmed)

                self._arm_idm(level, "bull")

                # إعادة تهيئة بعد CHoCh
                self.run_high_value, self.run_high_index = -np.inf, -1
                self.run_low_value, self.run_low_index = np.inf, -1
                self.pending_external_high = None
                self.pending_external_low = None

        # BOS+ / MSS+ — هبوط
        if last_low is not None and last_low["index"] < i:
            # استخدم قيمة ومؤشر LL المؤكَّد حصراً كمستوى الكسر
            level = float(last_low["value"])
            ref_index = int(last_low["index"])
            if i > 0 and (self.close[i - 1] > level + tol) and (self.close[i] <= level + tol):
                prev_state = self.t_MS
                event_type = "CHOCH+" if prev_state > 0 else "BOS+"
                direction = "bear"
                meta = {"level": level, "kind": "external_low", "label": last_low["label"]}
                self._record_event(i, event_type, direction, level, meta)
                self.t_MS = -1
                self._last_ext_event = (event_type, direction)
                self.isPrevBos = event_type == "BOS+"

                self._idm_y = float(level)
                self._idm_lsthl = float(self.last_internal_high["value"]) if self.last_internal_high else float("nan")

                # --- باتش A: لا تثبيت LL هنا، فقط نحفظ نية التثبيت حتى IDM ---
                self._pending_fix = {"side": "bear", "price": float(level), "index": ref_index}

                confirmed = self.last_external_low
                if confirmed is not None:
                    self._create_major_zone_from_sweep(i, "bear", confirmed)

                self._arm_idm(level, "bear")

                # إعادة تهيئة بعد CHoCh
                self.run_high_value, self.run_high_index = -np.inf, -1
                self.run_low_value, self.run_low_index = np.inf, -1
                self.pending_external_high = None
                self.pending_external_low = None

    # ------------------------------------------------------------------
    def _arm_idm(self, level: float, side: str) -> None:
        """Prime IDM gate using immediate references."""

        self.findIDM = True
        last_event = self._last_ext_event[0] if self._last_ext_event else None
        last_internal_low = self.last_internal_low["value"] if self.last_internal_low else float("nan")
        last_internal_high = self.last_internal_high["value"] if self.last_internal_high else float("nan")
        self._idm_ctx = {
            "side": side,
            "y": float(level),
            "lastL": float(last_internal_low),
            "lastH": float(last_internal_high),
            "last_event_ext": last_event,
            "was_prev_bos": bool(self.isPrevBos),
        }
        if side == "bull":
            ref = self.last_internal_low or (
                {"value": self.last_major_low_value, "index": self.last_major_low_index} if not math.isnan(self.last_major_low_value) else None
            )
            if ref:
                self.idmLow = ref["value"]
            self.idmHigh = np.nan
        else:
            ref = self.last_internal_high or (
                {"value": self.last_major_high_value, "index": self.last_major_high_index} if not math.isnan(self.last_major_high_value) else None
            )
            if ref:
                self.idmHigh = ref["value"]
            self.idmLow = np.nan

    # ------------------------------------------------------------------
    def _select_zone_idm_like_pine(self, side: str, y: float, lsthl: float, tol: float) -> Optional[Dict[str, Any]]:
        """Select IDM zone following Pine's y/lstHl gating."""

        if not (np.isfinite(y) and np.isfinite(lsthl)):
            return None

        picks: List[Tuple[float, Dict[str, Any]]] = []
        for zones in (self.major_bull, self.major_bear, self.minor_bull, self.minor_bear):
            for zone in zones:
                if zone.get("invalid") or zone.get("side") != side:
                    continue
                top = float(zone["top"])
                bottom = float(zone["bottom"])
                if side == "bull":
                    if top > y + tol or bottom < lsthl - tol:
                        continue
                    picks.append((top, zone))
                else:
                    if bottom < y - tol or top > lsthl + tol:
                        continue
                    picks.append((bottom, zone))
        if not picks:
            return None
        if side == "bull":
            return max(picks, key=lambda t: t[0])[1]
        return min(picks, key=lambda t: t[0])[1]

    # ------------------------------------------------------------------
    def _update_idm_and_obs(self, i: int) -> None:
        """Manage IDM triggers and zone lifecycle."""

        # منطق minor القديم كان ينشئ مناطق — أبقيناه للتوافق لكنه لا ينشئ مناطق الآن
        self._update_minor_state(i)

        tol = float(self.eq_threshold_series[i]) if self.eq_threshold_series is not None else 0.0

        if self.findIDM:
            ctx = self._idm_ctx or {}
            prev_was_bos = bool(ctx.get("was_prev_bos"))
            ctx_side = ctx.get("side")
            stype = self.structure_type.lower().strip()

            if not math.isnan(self.idmLow) and self.low[i] < self.idmLow - tol:
                if ctx_side and ctx_side != "bull":
                    return
                if self.t_MS <= 0:
                    return
                if stype == "choch with idm":
                    lastL = float(ctx.get("lastL", float("nan")))
                    if math.isnan(lastL) or not math.isclose(self.idmLow, lastL, rel_tol=0.0, abs_tol=tol):
                        return

                zone = self._select_zone_idm_like_pine("bull", self._idm_y, self._idm_lsthl, tol)
                if zone:
                    zone["kind"] = "idm"
                    zone.setdefault("touched", False)
                    zone.setdefault("mit_extended", False)
                    zone.setdefault("prev_close_relation", "none")
                    zone.setdefault("meta", {})["idm_trigger"] = i
                    self._record_event(i, "IDM", "bull", zone["top"], {"zone_id": zone["id"]})
                    self._record_event(i, "OB_IDM_BULL", "bull", zone["top"], {"zone_id": zone["id"]})

                pf = getattr(self, "_pending_fix", None)
                if pf and pf.get("side") == "bull":
                    hidx = int(pf.get("index", -1))
                    hh = float(pf.get("price", float("nan")))
                    if hidx >= 0 and np.isfinite(hh):
                        chosen_idx = hidx
                        chosen_val = hh
                        if prev_was_bos and self._ext_high_stack:
                            prev_pivot = self._ext_high_stack.pop()
                            chosen_idx = int(prev_pivot.get("index", chosen_idx))
                            chosen_val = float(prev_pivot.get("value", chosen_val))
                        if self.last_external_high is not None:
                            self._ext_high_stack.append(self.last_external_high.copy())
                        if 0 <= chosen_idx < self.length:
                            pivot = {
                                "index": chosen_idx,
                                "time": self.time_index[chosen_idx],
                                "kind": "high",
                                "value": chosen_val,
                                "label": "HH",
                            }
                            self.last_external_high = pivot
                            self.external_pivots.append(pivot)
                            self.last_major_high_value = chosen_val
                            self.last_major_high_index = chosen_idx
                    self._pending_fix = None

                self.findIDM = False
                self.idmLow = np.nan
                self._idm_y = float("nan")
                self._idm_lsthl = float("nan")
                self._idm_ctx = None
                self.isPrevBos = False

            elif not math.isnan(self.idmHigh) and self.high[i] > self.idmHigh + tol:
                if ctx_side and ctx_side != "bear":
                    return
                if self.t_MS >= 0:
                    return
                if stype == "choch with idm":
                    lastH = float(ctx.get("lastH", float("nan")))
                    if math.isnan(lastH) or not math.isclose(self.idmHigh, lastH, rel_tol=0.0, abs_tol=tol):
                        return

                zone = self._select_zone_idm_like_pine("bear", self._idm_y, self._idm_lsthl, tol)
                if zone:
                    zone["kind"] = "idm"
                    zone.setdefault("touched", False)
                    zone.setdefault("mit_extended", False)
                    zone.setdefault("prev_close_relation", "none")
                    zone.setdefault("meta", {})["idm_trigger"] = i
                    self._record_event(i, "IDM", "bear", zone["bottom"], {"zone_id": zone["id"]})
                    self._record_event(i, "OB_IDM_BEAR", "bear", zone["bottom"], {"zone_id": zone["id"]})

                pf = getattr(self, "_pending_fix", None)
                if pf and pf.get("side") == "bear":
                    lidx = int(pf.get("index", -1))
                    ll = float(pf.get("price", float("nan")))
                    if lidx >= 0 and np.isfinite(ll):
                        chosen_idx = lidx
                        chosen_val = ll
                        if prev_was_bos and self._ext_low_stack:
                            prev_pivot = self._ext_low_stack.pop()
                            chosen_idx = int(prev_pivot.get("index", chosen_idx))
                            chosen_val = float(prev_pivot.get("value", chosen_val))
                        if self.last_external_low is not None:
                            self._ext_low_stack.append(self.last_external_low.copy())
                        if 0 <= chosen_idx < self.length:
                            pivot = {
                                "index": chosen_idx,
                                "time": self.time_index[chosen_idx],
                                "kind": "low",
                                "value": chosen_val,
                                "label": "LL",
                            }
                            self.last_external_low = pivot
                            self.external_pivots.append(pivot)
                            self.last_major_low_value = chosen_val
                            self.last_major_low_index = chosen_idx
                    self._pending_fix = None

                self.findIDM = False
                self.idmHigh = np.nan
                self._idm_y = float("nan")
                self._idm_lsthl = float("nan")
                self._idm_ctx = None
                self.isPrevBos = False

        for zones, side in [
            (self.major_bull, "bull"),
            (self.major_bear, "bear"),
            (self.minor_bull, "bull"),
            (self.minor_bear, "bear"),
        ]:
            self._process_zones(zones, side, i)

    # ------------------------------------------------------------------
    def _select_zone(self, side: str, i: int) -> Optional[Dict[str, Any]]:
        """Return nearest zone compatible with IDM at bar i."""

        candidates = []
        price = self.close[i]
        zone_lists = [self.major_bull, self.major_bear, self.minor_bull, self.minor_bear]
        tol = float(self.eq_threshold_series[i]) if self.eq_threshold_series is not None else 0.0
        ctx = self._idm_ctx or {}
        y = float(ctx.get("y", float("nan")))
        lastL = float(ctx.get("lastL", float("nan")))
        lastH = float(ctx.get("lastH", float("nan")))

        for zones in zone_lists:
            for zone in zones:
                if zone.get("invalid"):
                    continue
                if zone.get("side") != side:
                    continue
                if zone.get("is_tested") and zone.get("tested_indices"):
                    last_test = zone["tested_indices"][-1]
                    if last_test == i:
                        continue
                if side == "bull":
                    if (not math.isnan(y) and zone["top"] > y + tol) or (
                        not math.isnan(lastL) and zone["bottom"] < lastL - tol
                    ):
                        continue
                    if zone["top"] > price + tol:
                        continue
                    diff = max(0.0, price - zone["top"])
                else:
                    if (not math.isnan(y) and zone["bottom"] < y - tol) or (
                        not math.isnan(lastH) and zone["top"] > lastH + tol
                    ):
                        continue
                    if zone["bottom"] < price - tol:
                        continue
                    diff = max(0.0, zone["bottom"] - price)
                priority = 0 if zone.get("is_validated") else 1
                candidates.append((priority, diff, zone))
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1]))
        return candidates[0][2]

    # ------------------------------------------------------------------
    def _update_minor_state(self, i: int) -> None:
        """DEPRECATED: لم يعد ينشئ مناطق؛ آلة الحالة تتكفل بتحديد الانعكاسات."""
        return

    def _get_minor_state(self, high: float, low: float) -> str:
        """Return Pine-style minor state classification."""
        if high >= self.top_ref and low <= self.bot_ref:
            return "notrend"
        if high >= self.top_ref and low > self.bot_ref:
            return "uptrend"
        if high < self.top_ref and low <= self.bot_ref:
            return "downtrend"
        return self.minor_state

    # ------------------------------------------------------------------
    def _resolve_minor_bounds(self, side: str, ref_index: int, reference: float) -> Tuple[float, float]:
        """Compute minor zone bounds per configuration."""

        open_price = self.open[ref_index]
        close_price = self.close[ref_index]
        high_price = self.high[ref_index]
        low_price = self.low[ref_index]
        body_high = max(open_price, close_price)
        body_low = min(open_price, close_price)

        mode = self.minor_bounds
        if mode not in {"body", "wick", "hybrid"}:
            mode = "wick"

        if side == "bull":
            if mode == "body":
                return float(body_high), float(body_low)
            if mode == "hybrid":
                return float(body_high), float(min(reference, low_price))
            return float(high_price), float(min(reference, low_price))

        if mode == "body":
            return float(body_high), float(body_low)
        if mode == "hybrid":
            return float(max(reference, high_price)), float(body_low)
        return float(max(reference, high_price)), float(low_price)

    # ------------------------------------------------------------------
    def _create_minor_zone(self, i: int, side: str, reference: float, ref_index: int) -> None:
        """DEPRECATED: منشئ المينور من تغيّر الحالة أُلغي لصالح السويب."""
        return

    # منشئ السويب ثنائي الجيران (+ Mother bar) للمينور
    def _detect_and_create_poi_zones_from_sweep(self, i: int) -> None:
        if i < 2 or i >= self.length:
            return

        b2 = i - 2
        prev_hi = self.high[b2 - 1] if b2 - 1 >= 0 else -np.inf
        prev_lo = self.low[b2 - 1] if b2 - 1 >= 0 else np.inf
        next_hi = self.high[b2 + 1] if b2 + 1 < self.length else -np.inf
        next_lo = self.low[b2 + 1] if b2 + 1 < self.length else np.inf

        # Mother bar: لو b2 داخل الشمعة السابقة، استخدم حدود الأم
        use_mother = False
        if b2 - 1 >= 0:
            mh = self.high[b2 - 1]
            ml = self.low[b2 - 1]
            if (self.high[b2] <= mh) and (self.low[b2] >= ml):
                use_mother = True
                self._mother_high, self._mother_low, self._mother_idx = mh, ml, b2 - 1

        if use_mother:
            box_top, box_bot, left_ix = float(self._mother_high), float(self._mother_low), int(self._mother_idx)
        else:
            box_top, box_bot, left_ix = float(self.high[b2]), float(self.low[b2]), b2

        # Supply sweep: high[b-2] أعلى من الجارين
        if (self.high[b2] > prev_hi) and (self.high[b2] > next_hi):
            zone_id = f"minor_supply_{left_ix}_{i}"
            candidate = {
                "id": zone_id,
                "side": "bear",
                "kind": "minor",
                "created_index": i,
                "created_time": self.time_index[i],
                "anchor_index": left_ix,
                "anchor_time": self.time_index[left_ix],
                "top": float(box_top),
                "bottom": float(box_bot),
                "is_validated": False,
                "is_tested": False,
                "invalid": False,
                "tested_indices": [],
                "mitigated_index": None,
                "extend_right": False if self.extend_on_break else True,
                "touched": False,
                "mit_extended": False,
                "prev_close_relation": "none",
                "meta": {},
            }
            self._merge_or_add_zone(candidate)

        # Demand sweep: low[b-2] أدنى من الجارين
        if (self.low[b2] < prev_lo) and (self.low[b2] < next_lo):
            zone_id = f"minor_demand_{left_ix}_{i}"
            candidate = {
                "id": zone_id,
                "side": "bull",
                "kind": "minor",
                "created_index": i,
                "created_time": self.time_index[i],
                "anchor_index": left_ix,
                "anchor_time": self.time_index[left_ix],
                "top": float(box_top),
                "bottom": float(box_bot),
                "is_validated": False,
                "is_tested": False,
                "invalid": False,
                "tested_indices": [],
                "mitigated_index": None,
                "extend_right": False if self.extend_on_break else True,
                "touched": False,
                "mit_extended": False,
                "prev_close_relation": "none",
                "meta": {},
            }
            self._merge_or_add_zone(candidate)

    # دمج/إضافة منطقة (يحافظ على منطقك الموجود للـ merge)
    def _merge_or_add_zone(self, candidate: Dict[str, Any]) -> None:
        candidate.setdefault("touched", False)
        candidate.setdefault("mit_extended", False)
        candidate.setdefault("prev_close_relation", "none")
        same_kind = [z for z in reversed(self.zone_objects) if z["kind"] == candidate["kind"] and z["side"] == candidate["side"]]
        if not same_kind:
            self.zone_objects.append(candidate)
            if candidate["kind"] == "major":
                (self.major_bull if candidate["side"] == "bull" else self.major_bear).append(candidate)
            else:
                (self.minor_bull if candidate["side"] == "bull" else self.minor_bear).append(candidate)
            return

        last = same_kind[0]
        last.setdefault("touched", False)
        inter_top = min(candidate["top"], last["top"])
        inter_bot = max(candidate["bottom"], last["bottom"])
        if inter_top > inter_bot:
            inter = inter_top - inter_bot
            base = max(abs(candidate["top"] - candidate["bottom"]), abs(last["top"] - last["bottom"]), 1e-12)
            ratio = inter / base
        else:
            ratio = 0.0
        included = (candidate["top"] >= last["top"]) and (candidate["bottom"] <= last["bottom"])
        if ratio >= 0.10 or included:  # نفس merge_ratio الافتراضي
            last["top"] = max(last["top"], candidate["top"])
            last["bottom"] = min(last["bottom"], candidate["bottom"])
            last["left_index"] = min(last.get("left_index", candidate["anchor_index"]), candidate["anchor_index"])
            last["right_index"] = max(last.get("right_index", candidate["created_index"]), candidate["created_index"])
        else:
            self.zone_objects.append(candidate)
            if candidate["kind"] == "major":
                (self.major_bull if candidate["side"] == "bull" else self.major_bear).append(candidate)
            else:
                (self.minor_bull if candidate["side"] == "bull" else self.minor_bear).append(candidate)

    # ------------------------------------------------------------------
    def _resolve_sweep_base_index(self, index: int) -> int:
        """Return base index for EXT zone respecting inside preference."""

        base = max(0, index - 2)
        if self.major_ext_inside_required:
            if base > 0:
                mother = base - 1
                if (
                    self.high[base] <= self.high[mother]
                    and self.low[base] >= self.low[mother]
                ):
                    return mother
            return -1
        return base

    # ------------------------------------------------------------------
    def _create_major_zone_from_sweep(self, i: int, side: str, pivot: Dict[str, Any]) -> None:
        """Create major zone using sweep-derived base candle with Pine-style gating."""

        if not pivot:
            return
        base_index = self._resolve_sweep_base_index(i)

        if base_index < 0 or base_index >= self.length:
            return

        zone_id = f"major_{side}_{base_index}_{pivot['index']}"
        if any(zone.get("id") == zone_id for zone in self.major_zone_objects):
            return

        body_high = max(self.open[base_index], self.close[base_index])
        body_low = min(self.open[base_index], self.close[base_index])
        high_price = self.high[base_index]
        low_price = self.low[base_index]

        if side == "bull":
            top = float(body_high)
            bottom = float(min(low_price, pivot["value"]))
        else:
            top = float(max(high_price, pivot["value"]))
            bottom = float(body_low)
        if bottom > top:
            bottom, top = top, bottom

        y = self._idm_y
        lsthl = self._idm_lsthl
        tol = float(self.eq_threshold_series[i]) if self.eq_threshold_series is not None else 0.0
        if np.isfinite(y) and np.isfinite(lsthl):
            if side == "bull":
                if not (top <= y + tol and bottom >= lsthl - tol):
                    return
            else:
                if not (bottom >= y - tol and top <= lsthl + tol):
                    return

        zone = {
            "id": zone_id,
            "side": side,
            "kind": "major",
            "created_index": i,
            "created_time": self.time_index[i],
            "anchor_index": base_index,
            "anchor_time": self.time_index[base_index],
            "top": top,
            "bottom": bottom,
            "is_validated": False,
            "is_tested": False,
            "invalid": False,
            "tested_indices": [],
            "mitigated_index": None,
            "extend_right": False if self.extend_on_break else True,
            "touched": False,
            "mit_extended": False,
            "prev_close_relation": "none",
            "meta": {"pivot_index": pivot["index"]},
        }
        self.zone_objects.append(zone)
        self.major_zone_objects.append(zone)
        if side == "bull":
            self.major_bull.append(zone)
            self._record_event(i, "OB_EXT_BULL", "bull", zone["top"], {"zone_id": zone_id})
        else:
            self.major_bear.append(zone)
            self._record_event(i, "OB_EXT_BEAR", "bear", zone["top"], {"zone_id": zone_id})

    # ------------------------------------------------------------------
    def _is_breaker(self, side: str, top: float, bottom: float, i: int, tol: float) -> bool:
        """Return True if candle i forms a breaker against the zone."""

        if i == 0:
            return False
        if side == "bear":
            return (self.close[i - 1] < top + tol) and (self.close[i] >= top + tol)
        return (self.close[i - 1] > bottom - tol) and (self.close[i] <= bottom - tol)

    # ------------------------------------------------------------------
    def _process_zones(self, zones: List[Dict[str, Any]], side: str, i: int) -> None:
        """Advance validation/testing/mitigation lifecycle."""

        if not zones:
            return

        price_high = self.high[i]
        price_low = self.low[i]
        price_close = self.close[i]
        tol = float(self.eq_threshold_series[i]) if self.eq_threshold_series is not None else 0.0

        to_remove = []
        for idx, zone in enumerate(zones):
            if zone.get("invalid"):
                to_remove.append(idx)
                continue

            validated = zone.get("is_validated", False)
            top = zone["top"]
            bottom = zone["bottom"]
            zone.setdefault("touched", False)
            zone.setdefault("mit_extended", False)
            prev_relation = zone.get("prev_close_relation", "none")

            if self.extend_on_range_cover and (price_high >= top) and (price_low <= bottom):
                zone["extend_right"] = True

            if not zone["touched"]:
                if side == "bull":
                    touched = price_low <= top + tol
                else:
                    touched = price_high >= bottom - tol
                if touched:
                    zone["touched"] = True
                    zkind = zone.get("kind", "")
                    touch_type = "OB_TOUCH_IDM" if zkind == "idm" else "OB_TOUCH_EXT"
                    touch_price = top if side == "bull" else bottom
                    self._record_event(i, touch_type, side, touch_price, {"zone_id": zone["id"]})

            if not validated:
                if side == "bull":
                    if price_high >= top - tol:
                        zone["is_validated"] = True
                        if self.extend_on_break:
                            zone["extend_right"] = True
                        self._record_event(i, "OB_VALIDATED", "bull", top, {"zone_id": zone["id"]})
                    elif price_low <= bottom - tol:
                        zone["invalid"] = True
                        self._record_event(i, "OB_INVALIDATED", "bull", bottom, {"zone_id": zone["id"]})
                        to_remove.append(idx)
                        continue
                else:
                    if price_low <= bottom + tol:
                        zone["is_validated"] = True
                        if self.extend_on_break:
                            zone["extend_right"] = True
                        self._record_event(i, "OB_VALIDATED", "bear", bottom, {"zone_id": zone["id"]})
                    elif price_high >= top + tol:
                        zone["invalid"] = True
                        self._record_event(i, "OB_INVALIDATED", "bear", top, {"zone_id": zone["id"]})
                        to_remove.append(idx)
                        continue
                continue

            if zone.get("is_tested") is False:
                if side == "bull" and i > 0 and (price_low < top - tol) and (self.low[i - 1] > top - tol):
                    zone["is_tested"] = True
                    zone["tested_indices"].append(i)
                    zone_copy = zone.copy()
                    zone_copy["tested_type"] = 1
                    self.tested_zones.append(zone_copy)
                    self._record_event(i, "OB_TESTED", "bull", top, {"zone_id": zone["id"]})
                    if zone["kind"] == "major":
                        self._record_event(i, "OF_MAJOR_BULL", "bull", top, {"zone_id": zone["id"]})
                    elif zone["kind"] == "minor":
                        self._record_event(i, "OF_MINOR_BULL", "bull", top, {"zone_id": zone["id"]})
                elif side == "bear" and i > 0 and (price_high > bottom + tol) and (self.high[i - 1] < bottom + tol):
                    zone["is_tested"] = True
                    zone["tested_indices"].append(i)
                    zone_copy = zone.copy()
                    zone_copy["tested_type"] = -1
                    self.tested_zones.append(zone_copy)
                    self._record_event(i, "OB_TESTED", "bear", bottom, {"zone_id": zone["id"]})
                    if zone["kind"] == "major":
                        self._record_event(i, "OF_MAJOR_BEAR", "bear", bottom, {"zone_id": zone["id"]})
                    elif zone["kind"] == "minor":
                        self._record_event(i, "OF_MINOR_BEAR", "bear", bottom, {"zone_id": zone["id"]})

            is_break = False
            if zone.get("is_tested"):
                is_break = self._is_breaker(side, top, bottom, i, tol)
            if is_break:
                zkind = zone.get("kind", "")
                brk_type = "OB_BREAK_IDM" if zkind == "idm" else "OB_BREAK_EXT"
                break_price = top if side == "bear" else bottom
                self._record_event(i, brk_type, side, break_price, {"zone_id": zone["id"]})
                if self.extend_on_break:
                    zone["extend_right"] = True

                opp = "bull" if side == "bear" else "bear"
                breaker_id = f"breaker_{opp}_{zone.get('anchor_index', i)}_{i}"
                if not any(z.get("id") == breaker_id for z in self.zone_objects):
                    new_zone = {
                        "id": breaker_id,
                        "side": opp,
                        "kind": zone.get("kind", "minor"),
                        "created_index": i,
                        "created_time": self.time_index[i],
                        "anchor_index": zone.get("anchor_index", i),
                        "anchor_time": zone.get("anchor_time", self.time_index[i]),
                        "top": top,
                        "bottom": bottom,
                        "is_validated": False,
                        "is_tested": False,
                        "invalid": False,
                        "tested_indices": [],
                        "mitigated_index": None,
                        "extend_right": zone.get("extend_right", False),
                        "touched": False,
                        "mit_extended": False,
                        "prev_close_relation": "none",
                        "meta": {"breaker_of": zone["id"]},
                    }
                    self.zone_objects.append(new_zone)
                    if new_zone["kind"] == "major":
                        (self.major_bull if opp == "bull" else self.major_bear).append(new_zone)
                    else:
                        (self.minor_bull if opp == "bull" else self.minor_bear).append(new_zone)

            if self.ob_mitig_rule == "touch":
                mitigated = (side == "bull" and price_low <= bottom + tol) or (side == "bear" and price_high >= top - tol)
            elif self.ob_mitig_rule == "wick":
                if side == "bull":
                    mitigated = (price_low < bottom - tol) and (self.close[i] > bottom + tol)
                else:
                    mitigated = (price_high > top + tol) and (self.close[i] < top - tol)
            elif self.ob_mitig_rule == "cross":
                if i > 0:
                    if side == "bear":
                        mitigated = (self.high[i] >= bottom - tol) and (self.high[i - 1] < bottom - tol)
                    else:
                        mitigated = (self.low[i] <= top + tol) and (self.low[i - 1] > top + tol)
                else:
                    mitigated = False
            elif self.ob_mitig_rule in ("close", "break"):
                mitigated = (side == "bull" and self.close[i] <= bottom + tol) or (side == "bear" and self.close[i] >= top - tol)
            else:
                mitigated = (side == "bull" and price_low <= bottom + tol) or (side == "bear" and price_high >= top - tol)

            if mitigated and not zone.get("mitigated_index"):
                zone["mitigated_index"] = i
                zone["mitigated_time"] = self.time_index[i]
                self._record_event(i, "OB_MITIGATED", side, bottom if side == "bull" else top, {"zone_id": zone["id"]})
                if (price_high >= top - tol) and (price_low <= bottom + tol):
                    zone["mit_extended"] = True
                    if self.extend_on_break:
                        zone["extend_right"] = True

            if zone.get("mit_extended"):
                if side == "bear":
                    if prev_relation == "below_bottom" and price_high > bottom - tol:
                        zone["mit_extended"] = False
                else:
                    if prev_relation == "above_top" and price_low < top + tol:
                        zone["mit_extended"] = False

            age = i - int(zone.get("anchor_index", i))
            if age > (self.len_factor * self.max_bar_history):
                zone["invalid"] = True
                to_remove.append(idx)
                continue

            if side == "bull" and price_high >= top + tol:
                zone["invalid"] = True
                to_remove.append(idx)
                continue
            if side == "bear" and price_low <= bottom - tol:
                zone["invalid"] = True
                to_remove.append(idx)
                continue

            if price_close > top + tol:
                zone["prev_close_relation"] = "above_top"
            elif price_close < bottom - tol:
                zone["prev_close_relation"] = "below_bottom"
            else:
                zone["prev_close_relation"] = "inside"

        for idx in reversed(to_remove):
            zones.pop(idx)

    # ------------------------------------------------------------------
    def _create_fvg(self, i: int) -> None:
        """Detect new fair value gaps (LTF + HTF)."""

        if i < 2:
            return

        atr = self.atr_series[i]
        min_gap = self.fvg_threshold * atr

        def build_gap(kind: str, upper: float, lower: float, tf: str, created_index: int) -> None:
            gap_size = abs(upper - lower)
            if gap_size < min_gap:
                return
            mid = (upper + lower) / 2.0
            gap = {
                "id": f"fvg_{tf}_{kind}_{created_index}_{len(self.fvgs)}",
                "created_index": created_index,
                "created_time": self.time_index[created_index],
                "side": "bull" if kind == "bull" else "bear",
                "upper": float(upper),
                "lower": float(lower),
                "mid": mid,
                "status": "active",
                "filled": False,
                "tf": tf,
                "delete_on_fill": self.fvg_delete_on_fill,
                "fill_rule": self.fvg_fill_rule,
                "touch_rule": self.fvg_touch_rule,
                "min_gap": gap_size,
            }
            self.fvgs.append(gap)
            event_type = "FVG_BULL" if kind == "bull" else "FVG_BEAR"
            self._record_event(created_index, event_type, "bull" if kind == "bull" else "bear", mid, {"fvg_id": gap["id"], "tf": tf})

        if self.low[i] > self.high[i - 2]:
            build_gap("bull", self.low[i], self.high[i - 2], "LTF", i)
        if self.high[i] < self.low[i - 2]:
            build_gap("bear", self.low[i - 2], self.high[i], "LTF", i)

        for mult in self.fvg_htf_multipliers:
            if mult <= 1:
                continue
            state = self.htf_state.get(mult, {})
            if not state:
                self.htf_state[mult] = {
                    "open": self.open[i],
                    "high": self.high[i],
                    "low": self.low[i],
                    "close": self.close[i],
                    "count": 1,
                    "start_index": i,
                }
                continue
            state["high"] = max(state["high"], self.high[i])
            state["low"] = min(state["low"], self.low[i])
            state["close"] = self.close[i]
            state["count"] += 1
            if state["count"] >= mult:
                bar = {
                    "open": state["open"],
                    "high": state["high"],
                    "low": state["low"],
                    "close": state["close"],
                    "end_index": i,
                }
                buf = self.htf_buffers[mult]
                buf.append(bar)
                self.htf_state[mult] = {}
                if len(buf) == 3:
                    older, mid_bar, newest = list(buf)
                    if newest["low"] > older["high"]:
                        build_gap("bull", newest["low"], older["high"], f"HTF_{mult}", i)
                    if newest["high"] < older["low"]:
                        build_gap("bear", older["low"], newest["high"], f"HTF_{mult}", i)

    # ------------------------------------------------------------------
    def _update_fvg_state(self, i: int) -> None:
        """Update active FVGs per fill rule."""

        if not self.fvgs:
            return

        price_high = self.high[i]
        price_low = self.low[i]
        price_close = self.close[i]

        for gap in self.fvgs:
            if gap["status"] != "active":
                continue
            side = gap["side"]
            upper = gap["upper"]
            lower = gap["lower"]
            mid = gap["mid"]
            filled = False
            rule = gap.get("fill_rule", self.fvg_fill_rule)

            if side == "bull":
                if rule == "midpoint":
                    filled = price_low <= mid
                elif rule == "touch":
                    filled = price_low <= lower
                elif rule == "wick":
                    filled = price_low <= lower
                else:  # close
                    filled = price_close <= lower
            else:
                if rule == "midpoint":
                    filled = price_high >= mid
                elif rule == "touch":
                    filled = price_high >= upper
                elif rule == "wick":
                    filled = price_high >= upper
                else:
                    filled = price_close >= upper

            if filled:
                gap["status"] = "filled"
                gap["filled"] = True
                gap["broken_index"] = i
                gap["broken_time"] = self.time_index[i]
                event_type = "FVG_BREAK_BULL" if side == "bull" else "FVG_BREAK_BEAR"
                self._record_event(i, event_type, side, mid, {"fvg_id": gap["id"]})

        if any(g.get("delete_on_fill") and g.get("filled") for g in self.fvgs):
            self.fvgs = [g for g in self.fvgs if not (g.get("delete_on_fill") and g.get("filled"))]

    # ------------------------------------------------------------------
    def _update_liquidity_levels(self, i: int) -> None:
        """Create and manage liquidity levels from pivots."""

        start = max(self._last_liq_added_idx + 1, 0)
        new_pivots = self.internal_pivots[start:]

        for pivot in new_pivots:
            level_id = (pivot["kind"], pivot["index"])
            if level_id in self.liquidity_levels:
                continue
            side = "low" if pivot["kind"] == "low" else "high"
            level = {
                "id": level_id,
                "side": side,
                "price": pivot["value"],
                "status": "active",
                "created_index": pivot["index"],
                "created_time": pivot["time"],
                "broken_index": None,
                "broken_time": None,
            }
            self.liquidity_levels[level_id] = level
            event = "LIQ_LOW" if side == "low" else "LIQ_HIGH"
            direction = "bull" if side == "low" else "bear"
            self._record_event(i, event, direction, pivot["value"], {"level_id": level_id})
        if new_pivots:
            self._last_liq_added_idx = len(self.internal_pivots) - 1

        for level in self.liquidity_levels.values():
            if level["status"] != "active":
                continue
            price = level["price"]
            tol = float(self.eq_threshold_series[i]) if self.eq_threshold_series is not None else 0.0
            if level["side"] == "high" and self.close[i] > price - tol:
                level["status"] = "broken"
                level["broken_index"] = i
                level["broken_time"] = self.time_index[i]
                self._record_event(i, "LIQ_BREAK_HIGH", "bull", price, {"level_id": level["id"]})
            elif level["side"] == "low" and self.close[i] < price + tol:
                level["status"] = "broken"
                level["broken_index"] = i
                level["broken_time"] = self.time_index[i]
                self._record_event(i, "LIQ_BREAK_LOW", "bear", price, {"level_id": level["id"]})

    # ------------------------------------------------------------------
    def _compute_key_levels(self, i: int) -> None:
        """Update PDH/PDL/MID."""

        if i == 0:
            return

        prev_day = (self.time_index[i] - pd.Timedelta(days=1)).normalize()
        if hasattr(self, "_daily") and prev_day in self._daily.index:
            self.key_levels["PDH"] = float(self._daily.loc[prev_day, "high"])
            self.key_levels["PDL"] = float(self._daily.loc[prev_day, "low"])

        hh = self.last_external_high["value"] if self.last_external_high is not None else (self.last_internal_high["value"] if self.last_internal_high else np.nan)
        ll = self.last_external_low["value"] if self.last_external_low is not None else (self.last_internal_low["value"] if self.last_internal_low else np.nan)
        if not math.isnan(hh) and not math.isnan(ll):
            self.key_levels["MID"] = (hh + ll) / 2.0

    # ------------------------------------------------------------------
    def _compute_ote_zone(self, i: int) -> None:
        """Store OTE range from latest swing pair."""

        if not self.enable_ote:
            return
        if self.last_external_high and self.last_external_low:
            hh = self.last_external_high["value"]
            ll = self.last_external_low["value"]
            if hh > ll:
                ote_low = ll + (hh - ll) * self.ote_lo
                ote_high = ll + (hh - ll) * self.ote_hi
                self.current_ote = (ote_low, ote_high)
                self.key_levels["OTE_LOW"] = ote_low
                self.key_levels["OTE_HIGH"] = ote_high

    # ------------------------------------------------------------------
    def _update_fvg_state_htf(self, i: int) -> None:
        """Placeholder for HTF gap syncing (not used)."""

        return


# =========================================================
# Binance HTTP Fetcher (بدون مفاتيح)
# =========================================================
class BinanceHTTP:
    BASE = "https://fapi.binance.com"

    @staticmethod
    def _map_tf(tf: str) -> str:
        allowed = {"1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d"}
        return tf if tf in allowed else "15m"

    @staticmethod
    def _get(url: str, params: dict, retries: int = 3, backoff: float = 0.8):
        for i in range(retries):
            try:
                r = requests.get(url, params=params, timeout=10)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                if i == retries-1:
                    print(f"[HTTP] error: {e}")
                    return None
                time.sleep(backoff*(i+1))
        return None

    def get_top_usdt_perps(self, max_symbols: int = 30) -> List[str]:
        url = f"{self.BASE}/fapi/v1/ticker/24hr"
        data = self._get(url, params={})
        if not data: return []
        usdt = [d for d in data if str(d.get("symbol","" )).endswith("USDT")]
        usdt.sort(key=lambda d: float(d.get("quoteVolume", 0.0)), reverse=True)
        return [d["symbol"] for d in usdt[:max_symbols]]

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
        url = f"{self.BASE}/fapi/v1/klines"
        params = {"symbol": symbol.upper(), "interval": self._map_tf(timeframe), "limit": int(limit)}
        raw = self._get(url, params)
        if not raw: return None
        cols = ["open_time","open","high","low","close","volume","close_time","qv","trades","tb_base","tb_quote","ignore"]
        df = pd.DataFrame(raw, columns=cols)
        df = df[["open_time","open","high","low","close","volume"]].copy()
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df.set_index("open_time", inplace=True)
        df.sort_index(inplace=True)
        df.dropna(inplace=True)
        return df

# ===== TickSize & Symbols helpers (USDT-M) =====
BASE = "https://fapi.binance.com"  # تأكد أنه موجود مرة واحدة فقط

def get_exchange_info() -> dict:
    import requests
    r = requests.get(BASE + "/fapi/v1/exchangeInfo", timeout=15)
    r.raise_for_status()
    return r.json()

def get_usdtm_symbols(all_perps: bool = True) -> list[str]:
    """
    يرجّع كل رموز عقود USDT-M الدائمة (PERPETUAL).
    لو all_perps=False يرجّع فقط الرامجة للتداول.
    """
    info = get_exchange_info()
    out = []
    for s in info.get("symbols", []):
        if not s.get("symbol","" ).endswith("USDT"):
            continue
        if s.get("contractType") != "PERPETUAL":
            continue
        if (not all_perps) and s.get("status") != "TRADING":
            continue
        out.append(s["symbol"])
    out.sort()
    return out

def get_tick_map() -> dict[str, float]:
    """
    يرجّع dict: symbol -> tickSize (كسِعر).
    يؤخذ من PRICE_FILTER.tickSize.
    """
    info = get_exchange_info()
    ticks = {}
    for s in info.get("symbols", []):
        sym = s.get("symbol","" )
        if not sym.endswith("USDT"):
            continue
        if s.get("contractType") != "PERPETUAL":
            continue
        tick = None
        for f in s.get("filters", []):
            if f.get("filterType") == "PRICE_FILTER":
                try:
                    tick = float(f.get("tickSize", "0"))
                except Exception:
                    tick = 0.0
                break
        if tick is None:
            tick = 0.0
        ticks[sym] = tick
    return ticks

# =========================================================
# ماسح Binance Futures + مُرسِل التنبيهات
# =========================================================
class FuturesScanner:
    def __init__(self,
                 timeframe="1m",
                 limit=200,
                 max_symbols=10,
                 symbol_override: str = "",
                 cfg: Optional[ScannerSettings] = None,
                 smc_params: Optional[Dict[str, Any]] = None):
        self.timeframe = timeframe
        self.limit = int(limit)
        self.max_symbols = int(max_symbols)
        self.symbol_override = symbol_override.strip().upper()
        self.cfg = cfg or ScannerSettings()
        self.fetcher = BinanceHTTP()
        self.tg = TelegramNotifier(self.cfg.tg_enable, self.cfg.tg_title_prefix)
        self.smc_params = smc_params or {}

    def _fmt_price(self, p: float) -> str:
        if p >= 100: return f"{p:.2f}"
        if p >= 1:   return f"{p:.4f}"
        return f"{p:.6f}"

    def _should_alert(self, ev_type: str) -> bool:
        return any([
            self.cfg.alert_bos and ev_type == "BOS",
            self.cfg.alert_choch and ev_type == "CHOCH",
            self.cfg.alert_bos_plus and ev_type == "BOS+",
            self.cfg.alert_mss_plus and ev_type == "MSS+",
            self.cfg.alert_idm and ev_type == "IDM",
            self.cfg.alert_ob_tested and ev_type == "OB_TESTED",
            self.cfg.alert_ob_mitigated and ev_type == "OB_MITIGATED",
            self.cfg.alert_ob_touch_ext and ev_type == "OB_TOUCH_EXT",
            self.cfg.alert_ob_touch_idm and ev_type == "OB_TOUCH_IDM",
            self.cfg.alert_ob_break_ext and ev_type == "OB_BREAK_EXT",
            self.cfg.alert_ob_break_idm and ev_type == "OB_BREAK_IDM",
        ])

    def _format_event(self, sym: str, tf: str, ev: SMCEvent) -> str:
        price = self._fmt_price(float(ev.price))
        tag = ev.type
        side = ev.direction
        return f"[{sym} {tf}] {tag} ({side}) @ {price}"

    def _print_summary(self, sym: str, tf: str, res: SMCResult):
        # إحصاءات سريعة مؤخراً
        if not res.events:
            print(f"[{sym} {tf}] No alerts. (No events)")
            return
        last_idx = max(e.index for e in res.events) if res.events else 0
        cutoff = max(0, last_idx - self.cfg.recent_bars + 1)
        recent = [e for e in res.events if e.index >= cutoff]
        c = defaultdict(int)
        for e in recent: c[e.type] += 1
        print(f"[{sym} {tf}] Summary for last {self.cfg.recent_bars} bars — " +
              " ".join(f"{k}:{v}" for k,v in sorted(c.items())))

    def run(self):
        # رموز
        if self.symbol_override:
            symbols = [self.symbol_override]
        else:
            symbols = self.fetcher.get_top_usdt_perps(self.max_symbols)
        if self.cfg.debug: print("[DEBUG] symbols:", symbols)
        if not symbols:
            print("[SCAN] Could not fetch any symbols. Check network connection.")
            return

        tf = self.timeframe; lim = self.limit
        for sym in symbols:
            if self.cfg.debug: print(f"[DEBUG] fetching {sym} {tf} limit={lim} ...", end="", flush=True)
            df = self.fetcher.fetch_ohlcv(sym, tf, lim)
            if self.cfg.debug: print(f" bars={0 if df is None else len(df)}")

            if df is None or df.empty:
                if self.cfg.verbose: print(f"[WARN] {sym} {tf} — No data.")
                continue

            engine = SMC(**self.smc_params)
            res = engine.fit_transform(df)

            if self.cfg.verbose:
                self._print_summary(sym, tf, res)

            # فلترة أحداث آخر N شموع
            last_bar = len(df) - 1
            cutoff = max(0, last_bar - self.cfg.recent_bars + 1)
            recent_events = [e for e in res.events if e.index >= cutoff]

            # إرسال/طباعة التنبيهات
            has_alert = False
            for ev in recent_events:
                if self._should_alert(ev.type):
                    msg = self._format_event(sym, tf, ev)
                    print(msg); has_alert = True
                    self.tg.send(f"{self.cfg.tg_title_prefix}: {msg}")

            if not has_alert and not self.cfg.verbose:
                print(f"[{sym} {tf}] No alerts within the last {self.cfg.recent_bars} bars.")

# =========================================================
# مثال تشغيل محلي (Synthetic) + CLI ماسح
# =========================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(prog="SMC + Binance Futures Scanner (single-file)")
    
    # Scanner args
    parser.add_argument("--timeframe", "-t", default="4h", help="1m, 3m, 5m, 15m, 1h, 4h, 1d ...")
    parser.add_argument("--limit", "-l", type=int, default=500, help="Number of historical candles (recommend >= 2000 for parity)")
    parser.add_argument("--max-symbols", "-n", type=int, default=100, help="Number of top USDT symbols by volume")
    parser.add_argument("--symbol", "-s", default="", help="Single symbol to run (e.g., BTCUSDT)")
    parser.add_argument("--recent", type=int, default=200, help="Inspect within the last N candles")
    parser.add_argument("--tg", action="store_true", default=False, help="Enable Telegram alerts")
    parser.add_argument("--verbose", "-v", action="store_true", default=False, help="Print summary")
    parser.add_argument("--debug", action="store_true", default=False, help="Enable debug prints")

    # Alert toggles
    parser.add_argument("--no-bos", action="store_true")
    parser.add_argument("--no-choch", action="store_true")
    parser.add_argument("--no-bos-plus", action="store_true")
    parser.add_argument("--yes-mss-plus", action="store_true")
    parser.add_argument("--no-idm", action="store_true")
    parser.add_argument("--yes-ob-tested", action="store_true")
    parser.add_argument("--no-ob-mitigated", action="store_true")
    parser.add_argument("--no-ob-touch-ext", action="store_true")
    parser.add_argument("--no-ob-touch-idm", action="store_true")
    parser.add_argument("--no-ob-break-ext", action="store_true")
    parser.add_argument("--no-ob-break-idm", action="store_true")

    # Core SMC parameters
    parser.add_argument("--swing", type=int, default=10)
    parser.add_argument("--leng", type=int, default=40)
    parser.add_argument("--eq-th", type=float, default=0.0)
    parser.add_argument("--atr-len", type=int, default=300)
    parser.add_argument("--enable-fvg", action="store_true", default=True)
    parser.add_argument("--enable-liq", action="store_true", default=True)
    parser.add_argument("--enable-key", action="store_true", default=True)
    parser.add_argument("--enable-ote", action="store_true", default=True)
    parser.add_argument("--enable-ob", action="store_true", default=True)
    parser.add_argument("--fvg-th", type=float, default=0.10)
    parser.add_argument("--fvg-fill", choices=["midpoint","touch","wick","close"], default="midpoint")
    parser.add_argument("--fvg-touch", choices=["touch","wick","close","midpoint"], default="touch")
    parser.add_argument("--ob-mitig", choices=["touch","wick","close","break","cross"], default="touch")
    parser.add_argument("--minor-bounds", choices=["wick","body","hybrid"], default="wick")
    parser.add_argument("--ext-inside", action="store_true", default=False, help="Require inside bar for EXT OB base candle")
    parser.add_argument("--no-range-extend", action="store_true", default=False, help="Disable box extension when candle range covers it")
    parser.add_argument("--no-extend-on-break", action="store_true", default=False, help="Disable box extension on breaker/validation")

    args = parser.parse_args()

    if args.tg and (not _get_secret("TELEGRAM_BOT_TOKEN") or not _get_secret("TELEGRAM_CHAT_ID")):
        print("[!] Telegram enabled but keys are missing. Disable with --tg or fill API_KEYS/ENV.")

    cfg = ScannerSettings(
        tg_enable=bool(args.tg),
        tg_title_prefix="SMC Alert",
        recent_bars=max(1, int(args.recent)),
        verbose=bool(args.verbose),
        debug=bool(args.debug),
        alert_bos=not args.no_bos,
        alert_choch=not args.no_choch,
        alert_bos_plus=not args.no_bos_plus,
        alert_mss_plus=bool(args.yes_mss_plus),
        alert_idm=not args.no_idm,
        alert_ob_tested=bool(args.yes_ob_tested),
        alert_ob_mitigated=not args.no_ob_mitigated,
        alert_ob_touch_ext=not args.no_ob_touch_ext,
        alert_ob_touch_idm=not args.no_ob_touch_idm,
        alert_ob_break_ext=not args.no_ob_break_ext,
        alert_ob_break_idm=not args.no_ob_break_idm,
    )

    smc_params = dict(
        lengSMC=int(args.leng),
        swingSize=int(args.swing),
        eq_threshold=float(args.eq_th),
        atr_len_eq=int(args.atr_len),
        enable_fvg=bool(args.enable_fvg),
        enable_liquidity=bool(args.enable_liq),
        enable_key_levels=bool(args.enable_key),
        enable_ote=bool(args.enable_ote),
        enable_ob=bool(args.enable_ob),
        fvg_threshold=float(args.fvg_th),
        fvg_fill_rule=args.fvg_fill,
        fvg_touch_rule=args.fvg_touch,
        ob_mitig_rule=args.ob_mitig,
        minor_bounds=args.minor_bounds,
        major_ext_inside_required=bool(args.ext_inside),
        extend_on_range_cover=not args.no_range_extend,
        extend_on_break=not args.no_extend_on_break,
    )

    scanner = FuturesScanner(timeframe=args.timeframe,
                             limit=args.limit,
                             max_symbols=args.max_symbols,
                             symbol_override=args.symbol,
                             cfg=cfg,
                             smc_params=smc_params)
    scanner.run()

# ---------------------------------------------------------
# Changelog:
# - Adjusted market structure breaks to use confirmed pivots with close-only tolerance and deferred FixAfter application.
# - Removed fallback selection for IDM order blocks; gating now enforces y/lstHL alignment only.
# - Added breaker guard requiring prior test and bar-to-bar close crossings with tolerance.
