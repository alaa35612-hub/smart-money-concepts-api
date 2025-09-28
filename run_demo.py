"""Run the Smart Money engine on OHLCV data from CSV."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Iterable, List

from dataclasses import asdict

from smart_money_monolith import Candle, Engine, Event


def read_csv(path: Path) -> Iterable[Candle]:
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            yield Candle(
                time=int(row["time"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0.0)),
            )


def write_events(path: Path, events: List[Event]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            data = {
                "time": event.time,
                "name": event.name,
                "side": event.side,
                "meta": event.meta,
            }
            fh.write(json.dumps(data, ensure_ascii=False) + "\n")


def write_zones_snapshot(path: Path, engine: Engine) -> None:
    snapshot = {
        "demand": [asdict(zone) for zone in engine.ob.demand],
        "supply": [asdict(zone) for zone in engine.ob.supply],
    }
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def write_parity_report(path: Path, events: List[Event]) -> None:
    counts: dict[str, int] = {}
    for event in events:
        counts[event.name] = counts.get(event.name, 0) + 1
    lines = ["# Parity Summary", "", "| Event | Count |", "| --- | ---: |"]
    for name, count in sorted(counts.items()):
        lines.append(f"| {name} | {count} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(input_csv: Path, output_dir: Path) -> None:
    engine = Engine()
    events: List[Event] = []
    for candle in read_csv(input_csv):
        events.extend(engine.on_candle(candle))
    output_dir.mkdir(parents=True, exist_ok=True)
    write_events(output_dir / "events.jsonl", events)
    write_zones_snapshot(output_dir / "zones_snapshot.json", engine)
    write_parity_report(output_dir / "parity_report.md", events)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path, help="Path to OHLCV csv file")
    parser.add_argument("output_dir", type=Path, help="Directory for generated artefacts")
    args = parser.parse_args()
    run(args.input_csv, args.output_dir)


if __name__ == "__main__":
    main()
