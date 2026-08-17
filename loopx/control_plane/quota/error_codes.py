from __future__ import annotations

import json


class QuotaCommandValidationError(ValueError):
    """Public-safe diagnostic for an invalid ``loopx quota`` invocation."""


def quota_error_code(exc: BaseException) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "quota_state_invalid_json"
    if isinstance(exc, QuotaCommandValidationError):
        return "quota_invalid_arguments"
    if isinstance(exc, PermissionError):
        return "quota_state_permission_denied"
    if isinstance(exc, OSError):
        return "quota_state_io_failed"
    if isinstance(exc, KeyError):
        return "quota_state_missing_field"
    if isinstance(exc, TypeError):
        return "quota_state_shape_error"
    return "quota_unexpected_collection_error"
