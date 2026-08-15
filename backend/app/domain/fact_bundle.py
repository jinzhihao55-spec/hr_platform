"""Immutable-by-construction calculator inputs for one report Run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Any, Mapping

import pandas as pd


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame()


@dataclass(frozen=True)
class FactBundle:
    report_date: date
    baseline_date: date
    rule_version: str
    employments: pd.DataFrame
    resignations: pd.DataFrame = field(default_factory=_empty_frame)
    releases: pd.DataFrame = field(default_factory=_empty_frame)
    recruitment: pd.DataFrame = field(default_factory=_empty_frame)
    events: pd.DataFrame = field(default_factory=_empty_frame)
    decisions: tuple[dict[str, Any], ...] = ()
    baseline_rows: Mapping[int, int] = field(default_factory=dict)
    tenure_snapshot_date: date | None = None
    tenure_rows: tuple[dict[str, Any], ...] = ()
    daily_reconciliation: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "employments",
            "resignations",
            "releases",
            "recruitment",
            "events",
        ):
            frame = getattr(self, name)
            object.__setattr__(self, name, frame.copy(deep=True))
        object.__setattr__(
            self,
            "baseline_rows",
            MappingProxyType(
                {
                    int(row): int(value)
                    for row, value in self.baseline_rows.items()
                    if value is not None
                }
            ),
        )
        object.__setattr__(
            self,
            "daily_reconciliation",
            MappingProxyType(dict(self.daily_reconciliation)),
        )
        object.__setattr__(
            self,
            "decisions",
            tuple(dict(decision) for decision in self.decisions),
        )
        object.__setattr__(
            self,
            "tenure_rows",
            tuple(dict(row) for row in self.tenure_rows),
        )
