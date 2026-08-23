"""Notification types -- immutable data structures and protocols."""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Protocol


class Level(IntEnum):
    """Notification severity. IntEnum for easy comparison."""

    INFO = 0
    WARNING = 1
    CRITICAL = 2


class NotificationChannel(Protocol):
    """Protocol for notification channel modules."""

    def is_configured(self) -> bool: ...

    def send(
        self,
        message: str,
        level: "Level",
        context: "NotificationContext | None",
        hostname: str,
        timestamp: str,
    ) -> bool: ...


@dataclass(frozen=True)
class NotificationContext:
    """Structured context attached to a notification."""

    score: int | None = None
    threshold: int | None = None
    gateway_ok: bool | None = None
    internet_ok_count: int | None = None
    internet_total: int | None = None
    reboot_count: int | None = None
    reboots_today: int | None = None
    max_reboots_per_day: int | None = None
    duration: str | None = None
    # Catégorie de routage ntfy : "alert" (défaut, alertes de ligne ->
    # NTFY_TOPIC) ou "ops" (cycle de vie, mises a jour, rapports ->
    # NTFY_TOPIC_OPS). Champ additionnel avec valeur par defaut : ne casse
    # aucun appelant existant de notify() ni la signature de notify().
    category: str = "alert"
    extra: dict[str, str] = field(default_factory=dict)


def format_context_inline(ctx: NotificationContext) -> str:
    """Format context as a compact key=value string."""
    parts: list[str] = []
    if ctx.score is not None:
        parts.append(f"score={ctx.score}/{ctx.threshold or '?'}")
    if ctx.gateway_ok is not None:
        parts.append(f"gw={'OK' if ctx.gateway_ok else 'KO'}")
    if ctx.internet_ok_count is not None:
        parts.append(f"inet={ctx.internet_ok_count}/{ctx.internet_total or '?'}")
    if ctx.reboot_count is not None:
        parts.append(f"reboots={ctx.reboot_count}")
    if ctx.reboots_today is not None:
        parts.append(
            f"reboots_today={ctx.reboots_today}/{ctx.max_reboots_per_day or '?'}"
        )
    if ctx.duration is not None:
        parts.append(f"duree={ctx.duration}")
    for k, v in ctx.extra.items():
        parts.append(f"{k}={v}")
    return " | ".join(parts)
