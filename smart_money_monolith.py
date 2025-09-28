"""Monolithic Smart Money engine module."""
from __future__ import annotations

"""Shared dataclasses for the Smart Money engine."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Optional


@dataclass(slots=True)
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(slots=True)
class Zone:
    left: int
    right: int
    top: float
    bottom: float
    side: str
    label: str = "EXT OB"
    mitigated_state: int = 0
    meta: Dict[str, object] = field(default_factory=dict)

    def height(self) -> float:
        return max(self.top - self.bottom, 0.0)


def to_decimal(value: float | Decimal) -> Decimal:
    """Return a ``Decimal`` representation for deterministic comparisons."""

    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

"""Event definitions for Smart Money engine."""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(slots=True)
class Event:
    """Represents an alert emitted by the analytical engine."""

    time: int
    name: str
    side: Optional[str] = None
    meta: Dict[str, object] = field(default_factory=dict)


class EventNames:
    """Canonical set of alert identifiers used by the engine."""

    # Market structure
    BOS_UP = "BOS_UP"
    BOS_DN = "BOS_DN"
    CHOCH_UP = "CHOCH_UP"
    CHOCH_DN = "CHOCH_DN"
    IDM_CONFIRMED = "IDM_CONFIRMED"

    # Order blocks
    OB_CREATED = "OB_CREATED"
    OB_MITIGATED = "OB_MITIGATED"
    OB_EXTENDED_ARMED = "OB_EXTENDED_ARMED"
    OB_EXTENDED_REMOVED = "OB_EXTENDED_REMOVED"
    BREAKER_CREATED = "BREAKER_CREATED"

    # Order flow
    OF_MAJOR_CREATED = "OF_MAJOR_CREATED"
    OF_MAJOR_TESTED = "OF_MAJOR_TESTED"
    OF_MINOR_CREATED = "OF_MINOR_CREATED"
    OF_MINOR_TESTED = "OF_MINOR_TESTED"

"""Runtime configuration for the Smart Money engine."""

from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    """Configuration flags mirroring the Pine Script inputs."""

    lenght: int = 40
    smc_structure_type_with_idm: bool = True
    extend_box_on_break: bool = True
    show_ext_ob: bool = True
    show_idm_ob: bool = True
    show_break_ext_and_idm_ob: bool = True
    show_major_of: bool = True
    show_minor_of: bool = True
    merge_ratio: float = 0.10
    max_obs: int = 24
    max_bar_history: int = 5_000
    price_tol: float = 1e-9

"""Market structure tracking for the Smart Money engine."""

from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from typing import List, Optional


getcontext().prec = 28


@dataclass(slots=True)
class StructureState:
    pu_high: Decimal = Decimal("0")
    pu_low: Decimal = Decimal("0")
    pu_h_bar: int = 0
    pu_l_bar: int = 0

    H: Decimal = Decimal("0")
    L: Decimal = Decimal("0")
    H_bar: int = 0
    L_bar: int = 0

    last_H: Decimal = Decimal("0")
    last_L: Decimal = Decimal("0")
    last_H_bar: int = 0
    last_L_bar: int = 0

    idm_high: Optional[Decimal] = None
    idm_low: Optional[Decimal] = None
    idm_h_bar: Optional[int] = None
    idm_l_bar: Optional[int] = None

    arr_top: List[Decimal] = field(default_factory=list)
    arr_bot: List[Decimal] = field(default_factory=list)
    arr_bar: List[int] = field(default_factory=list)

    arr_idm_high: List[Decimal] = field(default_factory=list)
    arr_idm_low: List[Decimal] = field(default_factory=list)
    arr_idm_h_bar: List[int] = field(default_factory=list)
    arr_idm_l_bar: List[int] = field(default_factory=list)

    arr_last_H: List[Decimal] = field(default_factory=list)
    arr_last_L: List[Decimal] = field(default_factory=list)
    arr_last_H_bar: List[int] = field(default_factory=list)
    arr_last_L_bar: List[int] = field(default_factory=list)

    mn_strc: Optional[bool] = None
    prev_mn_strc: Optional[bool] = None
    find_idm: bool = False
    is_bos_up: bool = False
    is_bos_dn: bool = False
    is_coc_up: bool = True
    is_coc_dn: bool = True
    is_prev_bos: bool = False

    prev_candle: Optional[Candle] = None
    H_lastLL: Optional[Decimal] = None
    L_lastHH: Optional[Decimal] = None


class MarketStructure:
    """Stateful Pine-compatible market structure interpreter."""

    def __init__(self, settings: Settings):
        self.S = settings
        self.state = StructureState()

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get(arr: List, n: int):
        return arr[-n] if len(arr) >= n else None

    def _push_topbot(self, t: int, h: Decimal, l: Decimal):
        st = self.state
        st.arr_top.append(h)
        st.arr_bot.append(l)
        st.arr_bar.append(t)

    def _push_idm_high(self):
        st = self.state
        if st.pu_high is not None:
            st.arr_idm_high.append(st.pu_high)
            st.arr_idm_h_bar.append(st.pu_h_bar)

    def _push_idm_low(self):
        st = self.state
        if st.pu_low is not None:
            st.arr_idm_low.append(st.pu_low)
            st.arr_idm_l_bar.append(st.pu_l_bar)

    def _push_last(self):
        st = self.state
        st.arr_last_H.append(st.last_H)
        st.arr_last_L.append(st.last_L)
        st.arr_last_H_bar.append(st.last_H_bar)
        st.arr_last_L_bar.append(st.last_L_bar)

    def reset_with_first(self, candle: Candle):
        st = self.state
        st.pu_high = to_decimal(candle.high)
        st.pu_low = to_decimal(candle.low)
        st.pu_h_bar = candle.time
        st.pu_l_bar = candle.time

        st.H = to_decimal(candle.high)
        st.L = to_decimal(candle.low)
        st.H_bar = candle.time
        st.L_bar = candle.time

        st.last_H = to_decimal(candle.high)
        st.last_L = to_decimal(candle.low)
        st.last_H_bar = candle.time
        st.last_L_bar = candle.time

        self._push_topbot(candle.time, to_decimal(candle.high), to_decimal(candle.low))
        st.prev_candle = candle

    # ------------------------------------------------------------------
    def step(self, candle: Candle) -> List[Event]:
        st = self.state
        events: List[Event] = []

        if st.prev_candle is None:
            self.reset_with_first(candle)
            return events

        t = candle.time
        o = to_decimal(candle.open)
        h = to_decimal(candle.high)
        l = to_decimal(candle.low)
        c = to_decimal(candle.close)

        prev = st.prev_candle
        po = to_decimal(prev.open)
        ph = to_decimal(prev.high)
        pl = to_decimal(prev.low)
        pc = to_decimal(prev.close)

        top = self._get(st.arr_top, 1) or h
        bot = self._get(st.arr_bot, 1) or l
        top1 = self._get(st.arr_top, 2) or h
        bot1 = self._get(st.arr_bot, 2) or l
        bar1 = self._get(st.arr_bar, 1) or t
        bar2 = self._get(st.arr_bar, 2) or t

        notrend = (h >= top and l <= bot)
        uptrend = (h >= top and l > bot)
        dtrend = (h < top and l <= bot)

        def is_green(close: Decimal, open_: Decimal) -> bool:
            return close > open_

        if notrend:
            if st.mn_strc is not None:
                st.prev_mn_strc = True if st.mn_strc else False
            else:
                if st.prev_mn_strc and is_green(c, o) and not is_green(pc, po):
                    st.pu_high = top
                    st.pu_h_bar = bar1
                    self._push_idm_low()
                if (st.prev_mn_strc is False) and (not is_green(c, o)) and is_green(pc, po):
                    st.pu_low = bot
                    st.pu_l_bar = bar1
                    self._push_idm_high()
            if l < st.L and is_green(c, o):
                self._push_idm_high()
            if h > st.H and not is_green(c, o):
                self._push_idm_low()

            self._push_topbot(t, h, l)
            st.pu_high, st.pu_low = h, l
            st.pu_h_bar = st.pu_l_bar = t
            st.mn_strc = None

        if uptrend:
            if (st.prev_mn_strc is True) and (st.mn_strc is None):
                st.pu_high = top1
                st.pu_h_bar = bar2
            if h > st.H:
                self._push_idm_low()
            self._push_topbot(t, h, l)
            st.pu_high = h
            st.pu_h_bar = t
            st.prev_mn_strc = None
            st.mn_strc = True

        if dtrend:
            if (st.prev_mn_strc is False) and (st.mn_strc is None):
                st.pu_low = bot1
                st.pu_l_bar = bar2
            if l < st.L:
                self._push_idm_high()
            self._push_topbot(t, h, l)
            st.pu_low = l
            st.pu_l_bar = t
            st.prev_mn_strc = None
            st.mn_strc = False

        # Update extremes
        if h >= st.H:
            st.H = h
            st.H_bar = t
            st.idm_low = self._get(st.arr_idm_low, 1)
            st.idm_l_bar = self._get(st.arr_idm_l_bar, 1)
            st.L_lastHH = l
        if l <= st.L:
            st.L = l
            st.L_bar = t
            st.idm_high = self._get(st.arr_idm_high, 1)
            st.idm_h_bar = self._get(st.arr_idm_h_bar, 1)
            st.H_lastLL = h

        def emit(name: str, side: Optional[str] = None, **meta) -> None:
            events.append(Event(time=t, name=name, side=side, meta=meta))

        def emit_structure(kind: str, is_up: bool) -> None:
            emit(EventNames.BOS_UP if (kind == "BOS" and is_up) else
                 EventNames.BOS_DN if (kind == "BOS" and not is_up) else
                 EventNames.CHOCH_UP if is_up else EventNames.CHOCH_DN)

        def confirm_idm(is_up: bool) -> None:
            emit(EventNames.IDM_CONFIRMED, side="UP" if is_up else "DOWN")

        # IDM confirmation
        if st.find_idm and st.is_coc_up and st.is_bos_up:
            ref = st.idm_low if st.idm_low is not None else l
            if l < ref:
                st.find_idm = False
                st.is_bos_up = False
                st.last_H = st.H
                st.last_H_bar = st.H_bar
                confirm_idm(True)
                self._push_last()
                st.L = l
                st.L_bar = t
                st.is_prev_bos = False

        if st.find_idm and st.is_coc_dn and st.is_bos_dn:
            ref = st.idm_high if st.idm_high is not None else h
            if h > ref:
                st.find_idm = False
                st.is_bos_dn = False
                st.last_L = st.L
                st.last_L_bar = st.L_bar
                confirm_idm(False)
                self._push_last()
                st.H = h
                st.H_bar = t
                st.is_prev_bos = False

        # CHOCH logic
        if st.is_coc_dn and h > st.last_H and c > st.last_H:
            emit_structure("CHOCH", True)
            st.find_idm = True
            st.is_bos_up = True
            st.is_coc_up = True
            st.is_bos_dn = False
            st.is_coc_dn = False
            st.is_prev_bos = False

        if st.is_coc_up and l < st.last_L and c < st.last_L:
            emit_structure("CHOCH", False)
            st.find_idm = True
            st.is_bos_dn = True
            st.is_coc_dn = True
            st.is_bos_up = False
            st.is_coc_up = False
            st.is_prev_bos = False

        # BOS logic
        if (not st.find_idm) and (not st.is_bos_up) and st.is_coc_up:
            if h > st.last_H and c > st.last_H:
                st.find_idm = True
                st.is_bos_up = True
                st.is_coc_up = True
                st.is_bos_dn = False
                st.is_coc_dn = False
                st.is_prev_bos = True
                emit_structure("BOS", True)

        if (not st.find_idm) and (not st.is_bos_dn) and st.is_coc_dn:
            if l < st.last_L and c < st.last_L:
                st.find_idm = True
                st.is_bos_dn = True
                st.is_coc_dn = True
                st.is_bos_up = False
                st.is_coc_up = False
                st.is_prev_bos = True
                emit_structure("BOS", False)

        if h > st.last_H:
            st.last_H = h
            st.last_H_bar = t
        if l < st.last_L:
            st.last_L = l
            st.last_L_bar = t

        st.prev_candle = candle
        return events

"""Order block lifecycle management."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional



@dataclass(slots=True)
class MotherState:
    high: Optional[float] = None
    low: Optional[float] = None
    bar: Optional[int] = None


class OrderBlocks:
    def __init__(self, settings: Settings):
        self.S = settings
        self.demand: List[Zone] = []
        self.supply: List[Zone] = []
        self.dem_mitigated: List[int] = []
        self.sup_mitigated: List[int] = []
        self.ext_bull_boxes: List[Zone] = []
        self.ext_bull_armed: List[bool] = []
        self.ext_bear_boxes: List[Zone] = []
        self.ext_bear_armed: List[bool] = []
        self.prev_high: Optional[float] = None
        self.prev_low: Optional[float] = None
        self.mother = MotherState()

    # ------------------------------------------------------------------
    def set_prev(self, candle: Candle) -> None:
        self.prev_high = candle.high
        self.prev_low = candle.low

    def register_mother_inside(self, candle: Candle) -> bool:
        ms = self.mother
        if ms.high is None:
            ms.high, ms.low, ms.bar = candle.high, candle.low, candle.time
            return False
        inside = candle.high < ms.high and candle.low > ms.low
        if not inside:
            ms.high, ms.low, ms.bar = candle.high, candle.low, candle.time
        return inside

    def _append_zone(self, zones: List[Zone], flags: List[int], zone: Zone) -> Zone:
        if zones:
            last = zones[-1]
            height = max(last.height(), 1e-12)
            top_close = abs(zone.top - last.top) / height < self.S.merge_ratio
            bot_close = abs(zone.bottom - last.bottom) / height < self.S.merge_ratio
            nested = (zone.top >= last.top and zone.bottom <= last.bottom) or (
                last.top >= zone.top and last.bottom <= zone.bottom
            )
            if nested or top_close or bot_close:
                last.left = min(last.left, zone.left)
                last.right = zone.right
                last.top = max(last.top, zone.top)
                last.bottom = min(last.bottom, zone.bottom)
                return last
        zones.append(zone)
        flags.append(0)
        if len(zones) > self.S.max_obs:
            zones.pop(0)
            flags.pop(0)
        return zone

    def add_sweep_zone(self, candle: Candle, reference: Candle, is_bull: bool) -> Optional[Event]:
        top = max(reference.high, candle.high)
        bottom = min(reference.low, candle.low)
        zone = Zone(
            left=reference.time,
            right=candle.time,
            top=float(top),
            bottom=float(bottom),
            side="DEMAND" if is_bull else "SUPPLY",
        )
        if is_bull:
            self._append_zone(self.demand, self.dem_mitigated, zone)
        else:
            self._append_zone(self.supply, self.sup_mitigated, zone)
        if (is_bull and not self.S.show_ext_ob) or ((not is_bull) and not self.S.show_ext_ob):
            return None
        return Event(time=candle.time, name=EventNames.OB_CREATED, side=zone.side, meta={
            "kind": "EXT",
            "top": zone.top,
            "bottom": zone.bottom,
        })

    def _push_extend(self, zone: Zone, broken_to_bull: bool) -> None:
        target = self.ext_bull_boxes if broken_to_bull else self.ext_bear_boxes
        armed = self.ext_bull_armed if broken_to_bull else self.ext_bear_armed
        target.insert(0, zone)
        armed.insert(0, False)

    def _remove_zone(self, zones: List[Zone], flags: List[int], idx: int, broken_to_bull: bool, now: int) -> None:
        zone = zones[idx]
        zone.right = now
        if self.S.extend_box_on_break and self.S.show_break_ext_and_idm_ob:
            self._push_extend(zone, broken_to_bull)
        zones.pop(idx)
        flags.pop(idx)

    def process_extend_boxes(self, candle: Candle) -> List[Event]:
        events: List[Event] = []
        if not self.S.extend_box_on_break:
            return events
        # Supply broken -> bull extend
        i = 0
        while i < len(self.ext_bull_boxes):
            zone = self.ext_bull_boxes[i]
            zone.right = candle.time
            if candle.close > zone.top and not self.ext_bull_armed[i]:
                self.ext_bull_armed[i] = True
                events.append(Event(candle.time, EventNames.OB_EXTENDED_ARMED, side="BULL", meta={
                    "top": zone.top,
                    "bottom": zone.bottom,
                }))
            if candle.low < zone.top and self.ext_bull_armed[i]:
                events.append(Event(candle.time, EventNames.OB_EXTENDED_REMOVED, side="BULL", meta={
                    "top": zone.top,
                    "bottom": zone.bottom,
                }))
                self.ext_bull_boxes.pop(i)
                self.ext_bull_armed.pop(i)
                i -= 1
            i += 1
        # Demand broken -> bear extend
        i = 0
        while i < len(self.ext_bear_boxes):
            zone = self.ext_bear_boxes[i]
            zone.right = candle.time
            if candle.close < zone.bottom and not self.ext_bear_armed[i]:
                self.ext_bear_armed[i] = True
                events.append(Event(candle.time, EventNames.OB_EXTENDED_ARMED, side="BEAR", meta={
                    "top": zone.top,
                    "bottom": zone.bottom,
                }))
            if candle.high > zone.bottom and self.ext_bear_armed[i]:
                events.append(Event(candle.time, EventNames.OB_EXTENDED_REMOVED, side="BEAR", meta={
                    "top": zone.top,
                    "bottom": zone.bottom,
                }))
                self.ext_bear_boxes.pop(i)
                self.ext_bear_armed.pop(i)
                i -= 1
            i += 1
        return events

    def process_zones(self, candle: Candle) -> List[Event]:
        events: List[Event] = []
        for zones, flags, is_supply in (
            (self.supply, self.sup_mitigated, True),
            (self.demand, self.dem_mitigated, False),
        ):
            i = len(zones) - 1
            while i >= 0:
                zone = zones[i]
                zone.right = candle.time
                # Breaker
                if is_supply and candle.low < zone.bottom and candle.close > zone.top:
                    breaker = Zone(zone.left, candle.time, zone.top, zone.bottom, "DEMAND", label="BREAKER")
                    self._append_zone(self.demand, self.dem_mitigated, breaker)
                    events.append(Event(candle.time, EventNames.BREAKER_CREATED, side="DEMAND", meta={
                        "top": breaker.top,
                        "bottom": breaker.bottom,
                    }))
                elif (not is_supply) and candle.high > zone.top and candle.close < zone.bottom:
                    breaker = Zone(zone.left, candle.time, zone.top, zone.bottom, "SUPPLY", label="BREAKER")
                    self._append_zone(self.supply, self.sup_mitigated, breaker)
                    events.append(Event(candle.time, EventNames.BREAKER_CREATED, side="SUPPLY", meta={
                        "top": breaker.top,
                        "bottom": breaker.bottom,
                    }))

                mitigated = False
                if is_supply:
                    if self.prev_high is not None and self.prev_high < zone.bottom and candle.high >= zone.bottom:
                        mitigated = True
                else:
                    if self.prev_low is not None and self.prev_low > zone.top and candle.low <= zone.top:
                        mitigated = True
                if mitigated and flags[i] < 2:
                    flags[i] = 2
                    zone.mitigated_state = 2
                    events.append(Event(candle.time, EventNames.OB_MITIGATED, side=zone.side, meta={
                        "top": zone.top,
                        "bottom": zone.bottom,
                    }))

                broken = (is_supply and candle.close > zone.top) or ((not is_supply) and candle.close < zone.bottom)
                if broken:
                    self._remove_zone(zones, flags, i, broken_to_bull=not is_supply, now=candle.time)
                i -= 1
        return events

    def tag_latest_idm(self, candle_time: int, side: str) -> Optional[Event]:
        zones = self.demand if side == "DEMAND" else self.supply
        flags = self.dem_mitigated if side == "DEMAND" else self.sup_mitigated
        if not zones:
            return None
        idx = len(zones) - 1
        zone = zones[idx]
        zone.label = "IDM OB"
        flags[idx] = max(flags[idx], 1)
        if (side == "DEMAND" and not self.S.show_idm_ob) or (side == "SUPPLY" and not self.S.show_idm_ob):
            return None
        return Event(candle_time, EventNames.OB_CREATED, side=zone.side, meta={
            "kind": "IDM",
            "top": zone.top,
            "bottom": zone.bottom,
        })

"""Order flow (major/minor) detection."""

from dataclasses import dataclass
from typing import List, Optional



@dataclass(slots=True)
class OFBox:
    left: int
    right: int
    top: float
    bottom: float
    side: str
    validated: bool = False


class OrderFlow:
    def __init__(self, settings: Settings):
        self.S = settings
        self.major_bull: List[OFBox] = []
        self.major_bear: List[OFBox] = []
        self.minor_bull: List[OFBox] = []
        self.minor_bear: List[OFBox] = []
        self.prev_hi: Optional[float] = None
        self.prev_lo: Optional[float] = None

    def set_prev(self, candle: Candle) -> None:
        self.prev_hi = candle.high
        self.prev_lo = candle.low

    def _append(self, lst: List[OFBox], cap: int, box: OFBox) -> None:
        lst.insert(0, box)
        if len(lst) > cap:
            lst.pop()

    def build_major(self, t: int, is_up: bool, last_high: float, last_low: float,
                    last_high_bar: int, last_low_bar: int,
                    helper_high: Optional[float], helper_low: Optional[float]) -> Optional[Event]:
        if is_up:
            top = float(last_high)
            bottom = float(helper_high if helper_high is not None else last_low)
            if top <= bottom:
                return None
            box = OFBox(left=last_high_bar or t, right=t, top=top, bottom=bottom, side="BULL")
            self._append(self.major_bull, self.S.show_major_of and self.S.max_obs or 0, box)
            return Event(t, EventNames.OF_MAJOR_CREATED, side="BULL", meta={"top": top, "bottom": bottom})
        top = float(helper_low if helper_low is not None else last_high)
        bottom = float(last_low)
        if top <= bottom:
            return None
        box = OFBox(left=last_low_bar or t, right=t, top=top, bottom=bottom, side="BEAR")
        self._append(self.major_bear, self.S.show_major_of and self.S.max_obs or 0, box)
        return Event(t, EventNames.OF_MAJOR_CREATED, side="BEAR", meta={"top": top, "bottom": bottom})

    def build_minor(self, t: int, trend: Optional[bool], top: float, bottom: float, bar: int) -> Optional[Event]:
        if trend is None or top <= bottom:
            return None
        if trend:
            box = OFBox(left=bar, right=t, top=float(top), bottom=float(bottom), side="BULL")
            self._append(self.minor_bull, self.S.show_minor_of and self.S.max_obs or 0, box)
            return Event(t, EventNames.OF_MINOR_CREATED, side="BULL", meta={"top": box.top, "bottom": box.bottom})
        box = OFBox(left=bar, right=t, top=float(top), bottom=float(bottom), side="BEAR")
        self._append(self.minor_bear, self.S.show_minor_of and self.S.max_obs or 0, box)
        return Event(t, EventNames.OF_MINOR_CREATED, side="BEAR", meta={"top": box.top, "bottom": box.bottom})

    def validate(self, t: int, high: float, low: float) -> List[Event]:
        events: List[Event] = []

        def loop(lst: List[OFBox], is_bull: bool, created_name: str, tested_name: str) -> None:
            i = 0
            while i < len(lst):
                box = lst[i]
                box.right = t
                if not box.validated:
                    if (is_bull and high > box.top) or ((not is_bull) and low < box.bottom):
                        box.validated = True
                else:
                    if is_bull:
                        if self.prev_lo is not None and self.prev_lo > box.top and low < box.top:
                            events.append(Event(t, tested_name, side="BULL", meta={"top": box.top, "bottom": box.bottom}))
                            lst.pop(i)
                            i -= 1
                    else:
                        if self.prev_hi is not None and self.prev_hi < box.bottom and high > box.bottom:
                            events.append(Event(t, tested_name, side="BEAR", meta={"top": box.top, "bottom": box.bottom}))
                            lst.pop(i)
                            i -= 1
                i += 1

        if self.S.show_major_of:
            loop(self.major_bull, True, EventNames.OF_MAJOR_CREATED, EventNames.OF_MAJOR_TESTED)
            loop(self.major_bear, False, EventNames.OF_MAJOR_CREATED, EventNames.OF_MAJOR_TESTED)
        if self.S.show_minor_of:
            loop(self.minor_bull, True, EventNames.OF_MINOR_CREATED, EventNames.OF_MINOR_TESTED)
            loop(self.minor_bear, False, EventNames.OF_MINOR_CREATED, EventNames.OF_MINOR_TESTED)
        return events

"""Co-ordinates the execution order for each candle."""

from dataclasses import dataclass, field
from typing import Callable, List, Optional



@dataclass(slots=True)
class Engine:
    settings: Settings = field(default_factory=Settings)
    on_event: Optional[Callable[[Event], None]] = None
    ms: MarketStructure = field(init=False)
    ob: OrderBlocks = field(init=False)
    of: OrderFlow = field(init=False)
    _events: List[Event] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ms", MarketStructure(self.settings))
        object.__setattr__(self, "ob", OrderBlocks(self.settings))
        object.__setattr__(self, "of", OrderFlow(self.settings))

    @property
    def events(self) -> List[Event]:
        return list(self._events)

    def _emit(self, event: Event) -> None:
        self._events.append(event)
        if self.on_event:
            self.on_event(event)

    def on_candle(self, candle: Candle) -> List[Event]:
        emitted: List[Event] = []

        # Step 0: capture previous candle for mitigation/tested logic
        prev_candle = self.ms.state.prev_candle
        if prev_candle is not None:
            self.ob.set_prev(prev_candle)
            self.of.set_prev(prev_candle)

        # Step 1: update mother/inside cache and generate sweep order blocks
        _ = self.ob.register_mother_inside(candle)
        if prev_candle is not None:
            if prev_candle.high > candle.high:
                evt = self.ob.add_sweep_zone(candle, prev_candle, is_bull=False)
                if evt:
                    emitted.append(evt)
            if prev_candle.low < candle.low:
                evt = self.ob.add_sweep_zone(candle, prev_candle, is_bull=True)
                if evt:
                    emitted.append(evt)

        # Step 2: market structure evaluation
        ms_events = self.ms.step(candle)
        for event in ms_events:
            emitted.append(event)

        # Step 3: tag IDM order blocks when confirmation arrives
        for event in ms_events:
            if event.name == EventNames.IDM_CONFIRMED and self.settings.smc_structure_type_with_idm:
                if event.side == "UP":
                    tag_evt = self.ob.tag_latest_idm(candle.time, "DEMAND")
                else:
                    tag_evt = self.ob.tag_latest_idm(candle.time, "SUPPLY")
                if tag_evt:
                    emitted.append(tag_evt)

        # Step 4: order block lifecycle updates
        for event in self.ob.process_extend_boxes(candle):
            emitted.append(event)
        for event in self.ob.process_zones(candle):
            emitted.append(event)

        # Step 5: order flow construction and validation
        last_ms_event = ms_events[-1] if ms_events else None
        if last_ms_event and last_ms_event.name in (EventNames.CHOCH_UP, EventNames.BOS_UP):
            evt = self.of.build_major(
                candle.time,
                True,
                float(self.ms.state.last_H),
                float(self.ms.state.last_L),
                self.ms.state.last_H_bar,
                self.ms.state.last_L_bar,
                float(self.ms.state.H_lastLL) if self.ms.state.H_lastLL is not None else None,
                float(self.ms.state.L_lastHH) if self.ms.state.L_lastHH is not None else None,
            )
            if evt:
                emitted.append(evt)
        if last_ms_event and last_ms_event.name in (EventNames.CHOCH_DN, EventNames.BOS_DN):
            evt = self.of.build_major(
                candle.time,
                False,
                float(self.ms.state.last_H),
                float(self.ms.state.last_L),
                self.ms.state.last_H_bar,
                self.ms.state.last_L_bar,
                float(self.ms.state.H_lastLL) if self.ms.state.H_lastLL is not None else None,
                float(self.ms.state.L_lastHH) if self.ms.state.L_lastHH is not None else None,
            )
            if evt:
                emitted.append(evt)

        top = self.ms._get(self.ms.state.arr_top, 1) or self.ms.state.pu_high
        bot = self.ms._get(self.ms.state.arr_bot, 1) or self.ms.state.pu_low
        bar = self.ms._get(self.ms.state.arr_bar, 1) or candle.time
        evt = self.of.build_minor(candle.time, self.ms.state.mn_strc, float(top), float(bot), bar)
        if evt:
            emitted.append(evt)
        for event in self.of.validate(candle.time, candle.high, candle.low):
            emitted.append(event)

        for event in emitted:
            self._emit(event)
        return emitted
