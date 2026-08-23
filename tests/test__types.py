"""Tests for notifier/_types.py -- NotificationContext.category (routage ntfy)."""

import dataclasses

from src.notifier._types import NotificationContext, format_context_inline


class TestNotificationContextCategory:
    def test_default_category_is_alert(self):
        ctx = NotificationContext()
        assert ctx.category == "alert"

    def test_category_can_be_set_to_ops(self):
        ctx = NotificationContext(category="ops")
        assert ctx.category == "ops"

    def test_existing_fields_unaffected_by_category(self):
        ctx = NotificationContext(score=5, threshold=10, category="ops")
        assert ctx.score == 5
        assert ctx.threshold == 10
        assert ctx.category == "ops"

    def test_replace_preserves_other_fields_and_overrides_category(self):
        ctx = NotificationContext(score=5, threshold=10)
        ops_ctx = dataclasses.replace(ctx, category="ops")
        assert ops_ctx.category == "ops"
        assert ops_ctx.score == 5
        assert ops_ctx.threshold == 10

    def test_format_context_inline_unaffected_by_category(self):
        ctx = NotificationContext(score=5, threshold=10, category="ops")
        assert format_context_inline(ctx) == "score=5/10"


class TestNotificationContextFrozenGuard:
    def test_cannot_mutate_category(self):
        import pytest

        ctx = NotificationContext()
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.category = "ops"  # type: ignore[misc]
