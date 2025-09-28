"""Basic behavioural checks for the Smart Money engine."""
from __future__ import annotations

import csv
import json

from smart_money_monolith import Candle, Engine, EventNames
from run_demo import run


def sample_candles():
    base = 1_700_000_000_000
    return [
        Candle(time=base + i * 60_000, open=1.0 + i * 0.1, high=1.1 + i * 0.1,
               low=0.9 + i * 0.05, close=1.05 + i * 0.1) for i in range(6)
    ]


def test_engine_emits_structure_events():
    engine = Engine()
    events = []
    for candle in sample_candles():
        events.extend(engine.on_candle(candle))
    names = {event.name for event in events}
    assert EventNames.CHOCH_UP in names or EventNames.BOS_UP in names


def test_run_demo_outputs(tmp_path):
    csv_path = tmp_path / "input.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["time", "open", "high", "low", "close"])
        for candle in sample_candles():
            writer.writerow([candle.time, candle.open, candle.high, candle.low, candle.close])
    output_dir = tmp_path / "out"
    run(csv_path, output_dir)
    events_path = output_dir / "events.jsonl"
    zones_path = output_dir / "zones_snapshot.json"
    parity_path = output_dir / "parity_report.md"
    assert events_path.exists()
    assert zones_path.exists()
    assert parity_path.exists()
    with events_path.open("r", encoding="utf-8") as fh:
        line = fh.readline()
        assert line
        data = json.loads(line)
        assert "name" in data
    snapshot = json.loads(zones_path.read_text(encoding="utf-8"))
    assert "demand" in snapshot and "supply" in snapshot
