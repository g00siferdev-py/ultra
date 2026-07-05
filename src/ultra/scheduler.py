from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

INTERVAL_RE = re.compile(r"^every\s+(\d+)\s*(m|min|mins|minutes|h|hr|hrs|hours)$", re.I)


@dataclass
class ScheduledTask:
    id: str
    prompt: str
    enabled: bool
    schedule_type: str  # interval | daily
    interval: timedelta | None
    daily_at: str | None  # HH:MM
    path: Path

    @classmethod
    def from_file(cls, path: Path) -> ScheduledTask:
        with path.open(encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}

        task_id = raw.get("id") or path.stem
        schedule = raw.get("schedule") or {}
        if isinstance(schedule, str):
            schedule = _parse_schedule_shorthand(schedule)

        schedule_type = schedule.get("type", "interval")
        interval = None
        daily_at = None

        if schedule_type == "interval":
            minutes = schedule.get("minutes")
            if minutes is None:
                raise ValueError(f"Task {task_id}: interval schedule needs 'minutes'")
            interval = timedelta(minutes=int(minutes))
        elif schedule_type == "daily":
            daily_at = schedule.get("at")
            if not daily_at:
                raise ValueError(f"Task {task_id}: daily schedule needs 'at' (HH:MM)")
        else:
            raise ValueError(f"Task {task_id}: unknown schedule type {schedule_type}")

        prompt = (raw.get("prompt") or "").strip()
        if not prompt:
            raise ValueError(f"Task {task_id}: prompt is required")

        return cls(
            id=task_id,
            prompt=prompt,
            enabled=bool(raw.get("enabled", True)),
            schedule_type=schedule_type,
            interval=interval,
            daily_at=str(daily_at) if daily_at else None,
            path=path,
        )


def _parse_schedule_shorthand(value: str) -> dict[str, Any]:
    match = INTERVAL_RE.match(value.strip())
    if not match:
        raise ValueError(f"Unsupported schedule shorthand: {value!r}")
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("h"):
        return {"type": "interval", "minutes": amount * 60}
    return {"type": "interval", "minutes": amount}


def load_tasks(tasks_dir: Path) -> list[ScheduledTask]:
    if not tasks_dir.is_dir():
        return []
    tasks: list[ScheduledTask] = []
    for path in sorted(tasks_dir.glob("*.yaml")):
        tasks.append(ScheduledTask.from_file(path))
    return tasks


class TaskState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, str] = {}
        if self.path.is_file():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def last_run(self, task_id: str) -> datetime | None:
        raw = self._data.get(task_id)
        if not raw:
            return None
        return datetime.fromisoformat(raw)

    def mark_run(self, task_id: str, when: datetime | None = None) -> None:
        ts = when or datetime.now(timezone.utc)
        self._data[task_id] = ts.isoformat()
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")


def is_due(task: ScheduledTask, state: TaskState, now: datetime | None = None) -> bool:
    if not task.enabled:
        return False

    now = now or datetime.now(timezone.utc)
    last = state.last_run(task.id)

    if task.schedule_type == "interval":
        assert task.interval is not None
        if last is None:
            return True
        return now - last >= task.interval

    if task.schedule_type == "daily":
        assert task.daily_at is not None
        hour, minute = [int(x) for x in task.daily_at.split(":", 1)]
        today_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if last is None:
            return now >= today_run
        if last.date() == now.date():
            return False
        return now >= today_run

    return False
