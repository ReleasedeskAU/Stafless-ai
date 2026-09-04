"""Unit tests for document-count argument parsing — no DB."""

from onyx.configs.constants import DocumentSource
from onyx.db.document_count import (
    DocumentCountError,
    escape_ilike_pattern,
    parse_count_source,
    parse_document_key,
    parse_filter_field,
    parse_filter_value,
    require_filter_field,
)
import pytest


def test_escape_ilike_pattern_neutralizes_wildcards() -> None:
    assert escape_ilike_pattern("Kabir") == "Kabir"
    assert escape_ilike_pattern("100%") == "100\\%"
    assert escape_ilike_pattern("a_b") == "a\\_b"
    assert escape_ilike_pattern("a\\b") == "a\\\\b"


def test_parse_count_source() -> None:
    assert parse_count_source(None) is None
    assert parse_count_source("all") is None
    assert parse_count_source("JIRA") is DocumentSource.JIRA
    with pytest.raises(DocumentCountError):
        parse_count_source("not-a-source")


def test_parse_filter_field_allowlist() -> None:
    assert parse_filter_field(None) is None
    assert parse_filter_field("Assignee") == "assignee"
    with pytest.raises(DocumentCountError):
        parse_filter_field("sql_injection")


def test_parse_filter_value_bounds() -> None:
    assert parse_filter_value(None) is None
    assert parse_filter_value("  Kabir  ") == "Kabir"
    with pytest.raises(DocumentCountError):
        parse_filter_value("   ")
    with pytest.raises(DocumentCountError):
        parse_filter_value("x" * 81)


def test_require_filter_field() -> None:
    assert require_filter_field("Status") == "status"
    with pytest.raises(DocumentCountError):
        require_filter_field(None)
    with pytest.raises(DocumentCountError):
        require_filter_field("  ")


def test_parse_document_key_exact_not_contains() -> None:
    assert parse_document_key("  RD-82  ") == "RD-82"
    with pytest.raises(DocumentCountError):
        parse_document_key(None)
    with pytest.raises(DocumentCountError):
        parse_document_key("   ")
    with pytest.raises(DocumentCountError):
        parse_document_key("RD-82\n")
    with pytest.raises(DocumentCountError):
        parse_document_key("x" * 41)

