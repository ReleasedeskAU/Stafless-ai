"""Catalog helpers for listing matching documents by tag."""

from onyx.db.document_catalog import catalog_document_row, ticket_key_from_semantic_id


def test_ticket_key_from_semantic_id() -> None:
    assert ticket_key_from_semantic_id("RD-63: Approvals missing") == "RD-63"
    assert ticket_key_from_semantic_id("RD-63 Approvals missing") == "RD-63"
    assert ticket_key_from_semantic_id("") is None
    assert ticket_key_from_semantic_id(None) is None


def test_catalog_document_row_prefers_key_tag() -> None:
    row = catalog_document_row(
        key="RD-10",
        semantic_id="OTHER-1: ignored title prefix",
        link="https://example.test/browse/RD-10",
    )
    assert row["key"] == "RD-10"
    assert row["title"] == "OTHER-1: ignored title prefix"
    assert row["link"] == "https://example.test/browse/RD-10"


def test_catalog_document_row_falls_back_to_semantic_prefix() -> None:
    row = catalog_document_row(
        key=None,
        semantic_id="RD-67: Conflicts not visible",
        link=None,
    )
    assert row["key"] == "RD-67"
    assert "Conflicts not visible" in (row["title"] or "")
