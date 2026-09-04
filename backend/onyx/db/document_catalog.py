"""Exact catalog queries on indexed Postgres tags — not OpenSearch top-N search.

Distinct values, group-by counts, key lookup, and filter lists share the same
unique-document census as document_count. Tags are the source of truth;
doc_metadata is unused.
"""

from __future__ import annotations

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.document_count import (
    ALLOWED_TAG_KEYS,
    DocumentCountError,
    MAX_CATALOG_ROWS,
    MAX_DOCUMENT_KEY_CHARS,
    PII_TAG_KEYS,
    _count_indexed_by_source,
    _resolve_filters,
    escape_ilike_pattern,
    matching_document_ids,
    queryable_fields,
)
from onyx.db.models import Connector, Document, DocumentByConnectorCredentialPair, Document__Tag, Tag

KEY_TAG = "key"


def ticket_key_from_semantic_id(semantic_id: str | None) -> str | None:
    """Best-effort ticket key from `RD-82: title` or `RD-82 title` semantic ids."""
    if not semantic_id:
        return None
    trimmed = semantic_id.strip()
    for sep in (": ", " "):
        if sep not in trimmed:
            continue
        prefix = trimmed.split(sep, 1)[0].strip()
        if prefix and len(prefix) <= MAX_DOCUMENT_KEY_CHARS:
            return prefix
    return None


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


def list_documents_matching_filter(
    db_session: Session,
    *,
    source: DocumentSource | None,
    filters: list[tuple[str, str]],
) -> dict[str, object]:
    """Exact indexed documents matching AND tag filters, with ticket keys.

    Same match rules as document-count. Results are capped; count is the full
    unique-document total so callers can say first 50 of N.

    Args:
        db_session: Tenant DB session.
        source: Restrict to this DocumentSource, or all sources.
        filters: Allow-listed field/value pairs combined with AND.

    Returns:
        count, documents[{key, title, link}], filters, truncated, cap.

    Raises:
        DocumentCountError: Empty filters.
    """
    if not filters:
        raise DocumentCountError("At least one filter is required")
    resolved = _resolve_filters(db_session, source, filters)
    if any(not item["matched_values"] for item in resolved):
        return _matching_list_payload([], 0, source, resolved, truncated=False)
    specs = [(str(item["filter_field"]), list(item["matched_values"])) for item in resolved]
    doc_ids = matching_document_ids(db_session, source, specs)
    true_count = len(doc_ids)
    truncated = true_count > MAX_CATALOG_ROWS
    documents = _documents_with_keys(db_session, doc_ids[:MAX_CATALOG_ROWS])
    return _matching_list_payload(
        documents, true_count, source, resolved, truncated=truncated
    )


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


def list_queryable_fields() -> dict[str, object]:
    """Published allow-list for Ask. Does not scan stored tag keys."""
    return queryable_fields()


def catalog_document_row(
    *,
    key: str | None,
    semantic_id: str | None,
    link: str | None,
) -> dict[str, str | None]:
    """One list-result document. Key tag wins; semantic_id prefix is the fallback."""
    resolved = (key or "").strip() or ticket_key_from_semantic_id(semantic_id)
    return {
        "key": resolved,
        "title": (semantic_id or "").strip() or resolved,
        "link": link,
    }


def _matching_list_payload(
    documents: list[dict[str, str | None]],
    count: int,
    source: DocumentSource | None,
    resolved: list[dict[str, object]],
    *,
    truncated: bool,
) -> dict[str, object]:
    first = resolved[0] if resolved else None
    return {
        "count": count,
        "returned": len(documents),
        "cap": MAX_CATALOG_ROWS,
        "source": source.value if source else "all",
        "filters": resolved,
        "filter_field": first["filter_field"] if first else None,
        "filter_value": first["filter_value"] if first else None,
        "matched_values": first["matched_values"] if first else [],
        "documents": documents,
        "truncated": truncated,
        "note": (
            f"Showing first {len(documents)} of {count} matching indexed documents."
            if truncated
            else "Exact indexed documents matching this filter, not a search sample."
        ),
    }


def _documents_with_keys(
    db_session: Session, doc_ids: list[str]
) -> list[dict[str, str | None]]:
    if not doc_ids:
        return []
    docs = {
        str(row.id): row
        for row in db_session.execute(select(Document).where(Document.id.in_(doc_ids))).scalars()
    }
    key_rows = db_session.execute(
        select(Document__Tag.document_id, Tag.tag_value)
        .join(Tag, Tag.id == Document__Tag.tag_id)
        .where(Document__Tag.document_id.in_(doc_ids))
        .where(Tag.tag_key == KEY_TAG)
    ).all()
    keys = {str(doc_id): str(value) for doc_id, value in key_rows}
    rows = [
        catalog_document_row(
            key=keys.get(doc_id),
            semantic_id=docs[doc_id].semantic_id,
            link=docs[doc_id].link,
        )
        for doc_id in doc_ids
        if doc_id in docs
    ]
    rows.sort(key=lambda row: (row.get("key") or "", row.get("title") or ""))
    return rows


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
        if tag_key in PII_TAG_KEYS or tag_key not in ALLOWED_TAG_KEYS:
            continue
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
