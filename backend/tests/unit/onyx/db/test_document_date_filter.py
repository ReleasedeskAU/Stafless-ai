"""Date-range matching on stored tag prefixes — no DB."""

from onyx.db.document_count import DocumentCountError
from onyx.db.document_date_filter import (
    DateRangeSpec,
    parse_date_bucket,
    parse_date_range_args,
    parse_iso_date,
    parse_sort_by,
    stored_date_in_range,
)
import pytest


def test_parse_iso_date_rejects_garbage() -> None:
    assert parse_iso_date(None, name="due") is None
    assert parse_iso_date("2026-09-05", name="due") == "2026-09-05"
    with pytest.raises(DocumentCountError):
        parse_iso_date("09/05/2026", name="due")
    with pytest.raises(DocumentCountError):
        parse_iso_date("2026-13-01", name="due")


def test_due_before_is_exclusive() -> None:
    spec = DateRangeSpec(
        field="duedate", start=None, end_inclusive=None, end_exclusive="2026-09-05"
    )
    assert stored_date_in_range("2026-09-04", spec) is True
    assert stored_date_in_range("2026-09-04T18:00:00.000+0000", spec) is True
    assert stored_date_in_range("2026-09-05", spec) is False
    assert stored_date_in_range("not-a-date", spec) is False


def test_created_range_is_inclusive() -> None:
    spec = DateRangeSpec(
        field="created",
        start="2026-08-01",
        end_inclusive="2026-08-31",
        end_exclusive=None,
    )
    assert stored_date_in_range("2026-08-01T00:00:00+0000", spec) is True
    assert stored_date_in_range("2026-08-31T23:59:59+0000", spec) is True
    assert stored_date_in_range("2026-09-01T00:00:00+0000", spec) is False
    assert stored_date_in_range("2026-07-31T00:00:00+0000", spec) is False


def test_parse_date_range_args_builds_due_before() -> None:
    specs = parse_date_range_args(due_before="2026-09-05")
    assert len(specs) == 1
    assert specs[0].field == "duedate"
    assert specs[0].end_exclusive == "2026-09-05"
    with pytest.raises(DocumentCountError):
        parse_date_range_args(created_from="2026-09-10", created_to="2026-09-01")


def test_sort_and_bucket_tokens() -> None:
    assert parse_sort_by(None) == "key_asc"
    assert parse_sort_by("updated_asc") == "updated_asc"
    assert parse_date_bucket("month") == "month"
    with pytest.raises(DocumentCountError):
        parse_sort_by("popularity")
    with pytest.raises(DocumentCountError):
        parse_date_bucket("week")
