"""Source registry and manifest tracking for production readiness."""
from __future__ import annotations

import csv
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class SourceEntry:
    source_id: str
    source_name: str
    source_family: str
    status: str
    rows: int
    sha256: str
    manifest_path: str
    lineage: Optional[str] = None
    blocker_reason: Optional[str] = None


class SourceRegistry:
    def __init__(self, root: Path):
        self.root = root
        self.registry_path = root / "data" / "review_queue" / "source_registry.csv"
        self.entries: Dict[str, SourceEntry] = {}

    def add_entry(self, entry: SourceEntry) -> None:
        self.entries[entry.source_id] = entry

    def write(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        with self.registry_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "source_id",
                    "source_name",
                    "source_family",
                    "status",
                    "rows",
                    "sha256",
                    "manifest_path",
                    "lineage",
                    "blocker_reason",
                ],
            )
            writer.writeheader()
            for entry in self.entries.values():
                writer.writerow(asdict(entry))

    def load(self) -> None:
        if not self.registry_path.exists():
            return
        with self.registry_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                self.entries[row["source_id"]] = SourceEntry(
                    source_id=row["source_id"],
                    source_name=row["source_name"],
                    source_family=row["source_family"],
                    status=row["status"],
                    rows=int(row["rows"]),
                    sha256=row["sha256"],
                    manifest_path=row["manifest_path"],
                    lineage=row.get("lineage"),
                    blocker_reason=row.get("blocker_reason"),
                )
