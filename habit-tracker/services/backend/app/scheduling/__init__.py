# [review:need-review] PHASE-03/108
# summary: the scheduling package surface — the job model, the registry and the runner; the scheduler itself lives in app/worker.py and is not exported here
"""
Фоновые задания: что они такое и как исполняется один прогон.

Планировщика здесь нет намеренно. Он один на систему и живёт в `app/worker.py`,
отдельным процессом; пакет, который умеет его поднять, рано или поздно был бы
импортирован веб-воркером.
"""

from app.scheduling.registry import (
    JobOutcome,
    JobRegistry,
    JobRunner,
    ScheduledJob,
    registry,
)

__all__ = [
    "JobOutcome",
    "JobRegistry",
    "JobRunner",
    "ScheduledJob",
    "registry",
]
