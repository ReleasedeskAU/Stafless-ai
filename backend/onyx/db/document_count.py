"""Exact unique-document counts from indexed Postgres tags — not OpenSearch top-N search.

StaffLess POST /admin/search always returns a sample (empty query: 10 random
chunks; keyword: NUM_RETURNED_HITS). OpenSearch can count, but the HTTP search
API does not expose _count. Unique document_id via document__tag is the census
used for how-many answers.
"""

from __future__ import annotations

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.models import Connector, DocumentByConnectorCredentialPair, Document__Tag, Tag

ALLOWED_TAG_KEYS = frozenset(
    {
        "assignee",
        "status",
        "priority",
        "project",
        "project_name",
        "labels",
        "issuetype",
        "reporter",
        "key",
    }
)
MAX_FILTER_VALUE_CHARS = 80
MAX_MATCHED_VALUES = 20
MAX_DOCUMENT_KEY_CHARS = 40
MAX_CATALOG_ROWS = 50


class DocumentCountError(ValueError):
    """Rejected count arguments (unknown field, empty value, etc.)."""


def escape_ilike_pattern(value: str) -> str:
    """Escape ILIKE wildcards so user input cannot broaden the match.

    Args:
        value: Raw filter substring.

    Returns:
        Pattern fragment safe to wrap in %...% with ESCAPE '\\'.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def parse_count_source(source: str | None) -> DocumentSource | None:
    """Map a wire source string to DocumentSource, or None for all sources.

    Raises:
        DocumentCountError: Unknown source name.
    """
    if source is None or source.strip() == "" or source.strip().lower() == "all":
        return None
    try:
        return DocumentSource(source.strip().lower())
    except ValueError as exc:
        raise DocumentCountError("Unknown source") from exc


def parse_filter_field(filter_field: str | None) -> str | None:
    """Allow-listed metadata tag key, or None for an unfiltered source total.

    Raises:
        DocumentCountError: Field is not in ALLOWED_TAG_KEYS.
    """
    if filter_field is None or filter_field.strip() == "":
        return None
    key = filter_field.strip().lower()
    if key not in ALLOWED_TAG_KEYS:
        raise DocumentCountError("Unknown filter field")
    return key


def require_filter_field(filter_field: str | None) -> str:
    """Allow-listed tag key; required for distinct/breakdown queries.

    Raises:
        DocumentCountError: Missing or unknown field.
    """
    key = parse_filter_field(filter_field)
    if key is None:
        raise DocumentCountError("Filter field is required")
    return key


def parse_document_key(key: str | None) -> str:
    """Exact ticket/document key (e.g. RD-82). Not a contains match.

    Raises:
        DocumentCountError: Empty or too long.
    """
    if key is None:
        raise DocumentCountError("Document key is empty")
    value = key.strip()
    if not value or "\n" in value or "\r" in value:
        raise DocumentCountError("Document key is empty")
    if len(value) > MAX_DOCUMENT_KEY_CHARS:
        raise DocumentCountError("Document key is too long")
    return value


def parse_filter_value(filter_value: str | None) -> str | None:
    """Non-empty filter substring, length-capped.

    Raises:
        DocumentCountError: Value is empty or too long.
    """
    if filter_value is None:
        return None
    value = filter_value.strip()
    if not value:
        raise DocumentCountError("Filter value is empty")
    if len(value) > MAX_FILTER_VALUE_CHARS:
        raise DocumentCountError("Filter value is too long")
    return value


def count_indexed_documents(
    db_session: Session,
    *,
    source: DocumentSource | None,
    filter_field: str | None,
    filter_value: str | None,
) -> dict[str, object]:
    """Exact unique indexed document count, optionally filtered by a metadata tag.

    Unfiltered counts use connector membership (has_been_indexed). Filtered
    counts use document__tag with case-insensitive contains on tag_value.

    Args:
        db_session: Tenant DB session.
        source: Restrict to this DocumentSource, or all sources.
        filter_field: Allow-listed tag key, or None.
        filter_value: Substring to match (e.g. Kabir matches Mohd Kabir).

    Returns:
        count, source, filter fields, and matched tag values (capped).

    Raises:
        DocumentCountError: filter_field set without filter_value or vice versa.
    """
    if (filter_field is None) != (filter_value is None):
        raise DocumentCountError("filter_field and filter_value must be sent together")

    if filter_field is None:
        count = _count_indexed_by_source(db_session, source)
        return _result(count, source, None, None, [])

    matched = _matching_tag_values(db_session, source, filter_field, filter_value)
    if not matched:
        return _result(0, source, filter_field, filter_value, [])
    count = _count_docs_for_tag_values(db_session, source, filter_field, matched)
    return _result(count, source, filter_field, filter_value, matched[:MAX_MATCHED_VALUES])


def _result(
    count: int,
    source: DocumentSource | None,
    filter_field: str | None,
    filter_value: str | None,
    matched_values: list[str],
) -> dict[str, object]:
    return {
        "count": count,
        "source": source.value if source else "all",
        "filter_field": filter_field,
        "filter_value": filter_value,
        "matched_values": matched_values,
        "note": "Exact unique indexed document count, not a search sample.",
    }


def _count_indexed_by_source(db_session: Session, source: DocumentSource | None) -> int:
    stmt = (
        select(func.count(distinct(DocumentByConnectorCredentialPair.id)))
        .select_from(DocumentByConnectorCredentialPair)
        .join(Connector, Connector.id == DocumentByConnectorCredentialPair.connector_id)
        .where(DocumentByConnectorCredentialPair.has_been_indexed.is_(True))
    )
    if source is not None:
        stmt = stmt.where(Connector.source == source)
    return int(db_session.execute(stmt).scalar_one())


def _matching_tag_values(
    db_session: Session,
    source: DocumentSource | None,
    filter_field: str,
    filter_value: str,
) -> list[str]:
    pattern = f"%{escape_ilike_pattern(filter_value)}%"
    stmt = (
        select(Tag.tag_value)
        .where(Tag.tag_key == filter_field)
        .where(Tag.tag_value.ilike(pattern, escape="\\"))
        .distinct()
        .limit(MAX_MATCHED_VALUES + 1)
    )
    if source is not None:
        stmt = stmt.where(Tag.source == source)
    return list(db_session.execute(stmt).scalars().all())


def _count_docs_for_tag_values(
    db_session: Session,
    source: DocumentSource | None,
    filter_field: str,
    tag_values: list[str],
) -> int:
    stmt = (
        select(func.count(distinct(Document__Tag.document_id)))
        .select_from(Document__Tag)
        .join(Tag, Tag.id == Document__Tag.tag_id)
        .join(
            DocumentByConnectorCredentialPair,
            DocumentByConnectorCredentialPair.id == Document__Tag.document_id,
        )
        .where(DocumentByConnectorCredentialPair.has_been_indexed.is_(True))
        .where(Tag.tag_key == filter_field)
        .where(Tag.tag_value.in_(tag_values))
    )
    if source is not None:
        stmt = stmt.where(Tag.source == source)
    return int(db_session.execute(stmt).scalar_one())
