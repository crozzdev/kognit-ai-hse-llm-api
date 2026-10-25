"""Unit tests for the warehouse exception taxonomy (src/kognit_llm/data).

Confirms ``translate`` maps each recognized psycopg error class to its
HTTP-facing ``WarehouseError`` subclass and that any unrecognized exception
fails closed as ``WarehouseUnavailable`` (R7.19-R7.34).
"""

import psycopg
import pytest

from kognit_llm.api.errors import (
    WarehousePrivilegeDenied,
    WarehouseStatementTimeout,
    WarehouseUnavailable,
    WarehouseUndefinedObject,
    WarehouseWriteRejected,
)
from kognit_llm.data.errors import translate


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (psycopg.errors.QueryCanceled(), WarehouseStatementTimeout),
        (psycopg.errors.ReadOnlySqlTransaction(), WarehouseWriteRejected),
        (psycopg.errors.InsufficientPrivilege(), WarehousePrivilegeDenied),
        (psycopg.errors.UndefinedTable(), WarehouseUndefinedObject),
        (psycopg.errors.UndefinedColumn(), WarehouseUndefinedObject),
        (psycopg.errors.UndefinedObject(), WarehouseUndefinedObject),
        (psycopg.errors.UndefinedFunction(), WarehouseUndefinedObject),
    ],
)
def test_translate_known_errors(exc, expected):
    assert isinstance(translate(exc), expected)


def test_translate_unknown_error_fails_closed_as_unavailable():
    assert isinstance(translate(ValueError("boom")), WarehouseUnavailable)


def test_translate_does_not_leak_original_detail():
    secret = "host=db.internal password=hunter2"
    translated = translate(RuntimeError(secret))
    assert secret not in str(translated)
