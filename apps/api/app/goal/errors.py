"""Goal-domain error types."""

from __future__ import annotations

from app.common.errors import APIError, ConflictError, NotFoundError


class GoalNotFoundError(NotFoundError):
    code = "goal_not_found"


class InvalidGoalStatusTransitionError(ConflictError):
    code = "invalid_goal_status_transition"


class GoalValidationError(APIError):
    status_code = 400
    code = "goal_validation_error"
