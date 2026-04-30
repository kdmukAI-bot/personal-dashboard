from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Status(Enum):
    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class ModuleResult:
    status: Status
    summary_text: str
    detail_text: str | None = None
    click_url: str | None = None
    data: dict = field(default_factory=dict)
    occurred_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "summary_text": self.summary_text,
            "detail_text": self.detail_text,
            "click_url": self.click_url,
            "data": self.data,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
        }
