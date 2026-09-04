"""Exact catalog queries on indexed Postgres tags — not OpenSearch top-N search.

Distinct values, group-by counts, and key lookup share the same unique-document
census as document_count. Tags are the source of truth; doc_metadata is unused.
"""

from __future__ import annotations

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.document_count import (
    ALLOWED_TAG_KEYS,
    MAX_CATALOG_ROWS,
    _count_indexed_by_source,
    escape_ilike_pattern,
)
from onyx.db.models import Connector, Document, DocumentByConnectorCredentialPair, Document__Tag, Tag

KEY_TAG = "key"


def list_distinct_tag_values(
    db_session: Session,
    *,
    source: DocumentSource | None,
    filter_field: str,
) -> dict[str, object]:
    """Distinct stored values for one allow-listed tag key on indexed documents.

    Args:
        db_session: Tenant DB session.
        source: Restrict to this DocumentSource, or all sources.
        filter_field: Allow-listed tag key.

    Returns:
        values, untagged_count, total_indexed, truncated flag.
    """
    groups, truncated = _group_counts(db_session, source, filter_field)
    total = _count_indexed_by_source(db_session, source)
    tagged = _count_docs_with_tag_key(db_session, source, filter_field)
    values = [row[0] for row in groups]
    return {
        "field": filter_field,
        "source": source.value if source else "all",
        "values": values,
        "untagged_count": max(0, total - tagged),
        "total_indexed": total,
        "truncated": truncated,
        "note": "Exact distinct indexed tag values, not a search sample.",
    }


def breakdown_by_tag(
    db_session: Session,
    *,
    source: DocumentSource | None,
    filter_field: str,
) -> dict[str, object]:
    """Exact unique-document counts grouped by one allow-listed tag key.

    A document with several list-tag values (labels) can appear in more than
    one group. untagged_count is indexed documents with no tag for this field.

    Args:
        db_session: Tenant DB session.
        source: Restrict to this DocumentSource, or all sources.
        filter_field: Allow-listed tag key.

    Returns:
        groups [{value, count}], untagged_count, total_indexed, truncated.
    """
    rows, truncated = _group_counts(db_session, source, filter_field)
    total = _count_indexed_by_source(db_session, source)
    tagged_docs = _count_docs_with_tag_key(db_session, source, filter_field)
    groups = [{"value": value, "count": count} for value, count in rows]
    return {
        "field": filter_field,
        "source": source.value if source else "all",
        "groups": groups,
        "untagged_count": max(0, total - tagged_docs),
        "total_indexed": total,
        "truncated": truncated,
        "note": "Exact unique indexed document counts grouped by field, not a search sample.",
    }


def lookup_document_by_key(
    db_session: Session,
    *,
    source: DocumentSource | None,
    key: str,
) -> dict[str, object]:
    """Exact indexed-document lookup by ticket/document key (e.g. RD-82).

    Matches the `key` tag case-insensitively, then semantic_id prefix `KEY:` / `KEY `.

    Args:
        db_session: Tenant DB session.
        source: Restrict to this DocumentSource, or all sources.
        key: Exact key string already validated by parse_document_key.

    Returns:
        found=False when missing; otherwise title, link, source, allow-listed fields.
    """
    doc = _find_by_key_tag(db_session, source, key) or _find_by_semantic_prefix(
        db_session, source, key
    )
    if doc is None:
        return {
            "found": False,
            "key": key,
            "source": source.value if source else "all",
            "note": "No indexed document with this exact key.",
        }
    return {
        "found": True,
        "key": key,
        "title": doc.semantic_id,
        "link": doc.link,
        "source": source.value if source else "all",
        "fields": _allowlisted_fields(db_session, doc.id),
        "note": "Exact indexed document lookup by key, not a search ranking.",
    }


def _group_counts(
    db_session: Session,
    source: DocumentSource | None,
    filter_field: str,
) -> tuple[list[tuple[str, int]], bool]:
    stmt = (
        select(Tag.tag_value, func.count(distinct(Document__Tag.document_id)))
        .select_from(Document__Tag)
        .join(Tag, Tag.id == Document__Tag.tag_id)
        .join(
            DocumentByConnectorCredentialPair,
            DocumentByConnectorCredentialPair.id == Document__Tag.document_id,
        )
        .where(DocumentByConnectorCredentialPair.has_been_indexed.is_(True))
        .where(Tag.tag_key == filter_field)
        .group_by(Tag.tag_value)
        .order_by(func.count(distinct(Document__Tag.document_id)).desc(), Tag.tag_value)
        .limit(MAX_CATALOG_ROWS + 1)
    )
    if source is not None:
        stmt = stmt.where(Tag.source == source)
    rows = [(str(value), int(count)) for value, count in db_session.execute(stmt).all()]
    truncated = len(rows) > MAX_CATALOG_ROWS
    return rows[:MAX_CATALOG_ROWS], truncated


def _count_docs_with_tag_key(
    db_session: Session,
    source: DocumentSource | None,
    filter_field: str,
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
    )
    if source is not None:
        stmt = stmt.where(Tag.source == source)
    return int(db_session.execute(stmt).scalar_one())


def _indexed_base(source: DocumentSource | None):
    stmt = (
        select(Document)
        .join(
            DocumentByConnectorCredentialPair,
            DocumentByConnectorCredentialPair.id == Document.id,
        )
        .join(Connector, Connector.id == DocumentByConnectorCredentialPair.connector_id)
        .where(DocumentByConnectorCredentialPair.has_been_indexed.is_(True))
    )
    if source is not None:
        stmt = stmt.where(Connector.source == source)
    return stmt


def _find_by_key_tag(
    db_session: Session, source: DocumentSource | None, key: str
) -> Document | None:
    stmt = (
        _indexed_base(source)
        .join(Document__Tag, Document__Tag.document_id == Document.id)
        .join(Tag, Tag.id == Document__Tag.tag_id)
        .where(Tag.tag_key == KEY_TAG)
        .where(func.lower(Tag.tag_value) == key.lower())
        .limit(1)
    )
    if source is not None:
        stmt = stmt.where(Tag.source == source)
    return db_session.execute(stmt).scalars().first()


def _find_by_semantic_prefix(
    db_session: Session, source: DocumentSource | None, key: str
) -> Document | None:
    escaped = escape_ilike_pattern(key)
    stmt = _indexed_base(source).where(
        or_(
            Document.semantic_id.ilike(f"{escaped}:%", escape="\\"),
            Document.semantic_id.ilike(f"{escaped} %", escape="\\"),
        )
    ).limit(1)
    return db_session.execute(stmt).scalars().first()


def _allowlisted_fields(db_session: Session, document_id: str) -> dict[str, str | list[str]]:
    stmt = (
        select(Tag.tag_key, Tag.tag_value, Tag.is_list)
        .select_from(Document__Tag)
        .join(Tag, Tag.id == Document__Tag.tag_id)
        .where(Document__Tag.document_id == document_id)
        .where(Tag.tag_key.in_(ALLOWED_TAG_KEYS))
        .order_by(Tag.tag_key, Tag.tag_value)
    )
    fields: dict[str, str | list[str]] = {}
    for tag_key, tag_value, is_list in db_session.execute(stmt):
        _append_field(fields, tag_key, tag_value, bool(is_list))
    return fields


def _append_field(
    fields: dict[str, str | list[str]], tag_key: str, tag_value: str, is_list: bool
) -> None:
    if not is_list and tag_key != "labels":
        fields[tag_key] = tag_value
        return
    current = fields.get(tag_key)
    if isinstance(current, list):
        current.append(tag_value)
    elif current is None:
        fields[tag_key] = [tag_value]
    else:
        fields[tag_key] = [current, tag_value]
