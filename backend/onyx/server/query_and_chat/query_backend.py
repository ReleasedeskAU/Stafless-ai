from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.chat_configs import NUM_RETURNED_HITS
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import IndexFilters, SearchDoc
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.db.document_catalog import (
    breakdown_by_tag,
    list_distinct_tag_values,
    lookup_document_by_key,
)
from onyx.db.document_count import (
    DocumentCountError,
    count_indexed_documents,
    parse_count_source,
    parse_document_key,
    parse_filter_field,
    parse_filter_value,
    require_filter_field,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.search_settings import get_current_search_settings
from onyx.db.tag import find_tags
from onyx.document_index.factory import get_default_document_index
from onyx.server.query_and_chat.models import (
    AdminSearchRequest,
    AdminSearchResponse,
    SourceTag,
    TagResponse,
)
from onyx.server.utils_vector_db import require_vector_db
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

admin_router = APIRouter(prefix="/admin")
basic_router = APIRouter(prefix="/query")


class DocumentCountRequest(BaseModel):
    """Exact unique-document count. Extra fields are rejected."""

    model_config = ConfigDict(extra="forbid")
    source: str | None = Field(default=None, max_length=40)
    filter_field: str | None = Field(default=None, max_length=40)
    filter_value: str | None = Field(default=None, max_length=80)


@admin_router.post("/document-count")
def document_count(
    body: DocumentCountRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> dict[str, object]:
    """Exact unique indexed document count. Not a search-hit sample.

    Uses Postgres connector membership and document tags (assignee, status, …).
    Partial filter_value matches (Kabir → Mohd Kabir).
    """
    try:
        return count_indexed_documents(
            db_session,
            source=parse_count_source(body.source),
            filter_field=parse_filter_field(body.filter_field),
            filter_value=parse_filter_value(body.filter_value),
        )
    except DocumentCountError:
        raise HTTPException(status_code=400, detail="Invalid count request") from None


class DocumentFieldRequest(BaseModel):
    """Distinct values or group-by for one metadata field. Extra fields rejected."""

    model_config = ConfigDict(extra="forbid")
    source: str | None = Field(default=None, max_length=40)
    field: str = Field(max_length=40)


class DocumentByKeyRequest(BaseModel):
    """Exact document lookup by ticket/document key. Extra fields rejected."""

    model_config = ConfigDict(extra="forbid")
    source: str | None = Field(default=None, max_length=40)
    key: str = Field(max_length=40)


@admin_router.post("/document-distinct")
def document_distinct(
    body: DocumentFieldRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> dict[str, object]:
    """Exact distinct tag values for one field on indexed documents."""
    try:
        return list_distinct_tag_values(
            db_session,
            source=parse_count_source(body.source),
            filter_field=require_filter_field(body.field),
        )
    except DocumentCountError:
        raise HTTPException(status_code=400, detail="Invalid catalog request") from None


@admin_router.post("/document-breakdown")
def document_breakdown(
    body: DocumentFieldRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> dict[str, object]:
    """Exact unique-document counts grouped by one metadata field."""
    try:
        return breakdown_by_tag(
            db_session,
            source=parse_count_source(body.source),
            filter_field=require_filter_field(body.field),
        )
    except DocumentCountError:
        raise HTTPException(status_code=400, detail="Invalid catalog request") from None


@admin_router.post("/document-by-key")
def document_by_key(
    body: DocumentByKeyRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> dict[str, object]:
    """Exact indexed document lookup by ticket key (not ranked search)."""
    try:
        return lookup_document_by_key(
            db_session,
            source=parse_count_source(body.source),
            key=parse_document_key(body.key),
        )
    except DocumentCountError:
        raise HTTPException(status_code=400, detail="Invalid catalog request") from None


@admin_router.post("/search", dependencies=[Depends(require_vector_db)])
def admin_search(
    question: AdminSearchRequest,
    user: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> AdminSearchResponse:
    tenant_id = get_current_tenant_id()

    query = question.query
    logger.notice("Received admin search query: %s", query)
    user_acl_filters = build_access_filters_for_user(user, db_session)

    final_filters = IndexFilters(
        source_type=question.filters.source_type,
        document_set=question.filters.document_set,
        created_at_range=question.filters.created_at_range,
        updated_at_range=question.filters.updated_at_range,
        tags=question.filters.tags,
        access_control_list=user_acl_filters,
        tenant_id=tenant_id,
    )
    search_settings = get_current_search_settings(db_session)
    # This flow is for search so we do not get all indices.
    document_index = get_default_document_index(search_settings, None, db_session)

    if not query or query.strip() == "":
        matching_chunks = document_index.random_retrieval(filters=final_filters)
    else:
        matching_chunks = document_index.keyword_retrieval(
            query=query,
            filters=final_filters,
            num_to_retrieve=NUM_RETURNED_HITS,
            # Admin search should expose hidden documents so admins can inspect
            # / unhide them.
            include_hidden=True,
        )

    documents = SearchDoc.from_chunks_or_sections(matching_chunks)

    # Deduplicate documents by id
    deduplicated_documents: list[SearchDoc] = []
    seen_documents: set[str] = set()
    for document in documents:
        if document.document_id not in seen_documents:
            deduplicated_documents.append(document)
            seen_documents.add(document.document_id)
    return AdminSearchResponse(documents=deduplicated_documents)


@basic_router.get("/valid-tags")
def get_tags(
    match_pattern: str | None = None,
    # If this is empty or None, then tags for all sources are considered
    sources: list[DocumentSource] | None = None,
    allow_prefix: bool = True,  # This is currently the only option
    limit: int = 50,
    _: User = Depends(require_permission(Permission.READ_SEARCH)),
    db_session: Session = Depends(get_session),
) -> TagResponse:
    if not allow_prefix:
        raise NotImplementedError("Cannot disable prefix match for now")

    key_prefix = match_pattern
    value_prefix = match_pattern
    require_both_to_match = False

    # split on = to allow the user to type in "author=bob"
    EQUAL_PAT = "="
    if match_pattern and EQUAL_PAT in match_pattern:
        split_pattern = match_pattern.split(EQUAL_PAT)
        key_prefix = split_pattern[0]
        value_prefix = EQUAL_PAT.join(split_pattern[1:])
        require_both_to_match = True

    db_tags = find_tags(
        tag_key_prefix=key_prefix,
        tag_value_prefix=value_prefix,
        sources=sources,
        limit=limit,
        db_session=db_session,
        require_both_to_match=require_both_to_match,
    )
    server_tags = [
        SourceTag(
            tag_key=db_tag.tag_key, tag_value=db_tag.tag_value, source=db_tag.source
        )
        for db_tag in db_tags
    ]
    return TagResponse(tags=server_tags)
