"""Overlay checks that do not import the full backend graph.

Full email/OpenAPI tests live in test_email_branding.py and
test_openapi_branding.py and need the backend venv. This file traces the
foss MIT path: invitation/reset/verify subjects use
ONYX_DEFAULT_APPLICATION_NAME, and /docs gets that name as the OpenAPI title.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.configs.constants import ONYX_DEFAULT_APPLICATION_NAME

_BACKEND = Path(__file__).resolve().parents[4]


def test_default_application_name_is_staffless_ai() -> None:
    assert ONYX_DEFAULT_APPLICATION_NAME == "StaffLess AI"
    assert "Onyx" not in ONYX_DEFAULT_APPLICATION_NAME


def test_email_utils_foss_path_uses_default_application_name() -> None:
    text = (_BACKEND / "onyx" / "auth" / "email_utils.py").read_text(encoding="utf-8")
    assert text.count("application_name = ONYX_DEFAULT_APPLICATION_NAME") >= 3
    assert 'subject = f"Invitation to Join {application_name} Organization"' in text
    assert 'subject = f"Reset Your {application_name} Password"' in text
    assert 'subject = f"{application_name} Email Verification"' in text
    invite_line = (
        "join an organization on {application_name}."
    )
    assert invite_line in text


def test_invite_and_reset_subjects_render_staffless_ai() -> None:
    application_name = ONYX_DEFAULT_APPLICATION_NAME
    invite = f"Invitation to Join {application_name} Organization"
    reset = f"Reset Your {application_name} Password"
    verify = f"{application_name} Email Verification"
    body = (
        f"You have been invited by admin@example.com to join an organization "
        f"on {application_name}."
    )
    assert invite == "Invitation to Join StaffLess AI Organization"
    assert reset == "Reset Your StaffLess AI Password"
    assert verify == "StaffLess AI Email Verification"
    assert "StaffLess AI" in body
    assert "Onyx" not in invite
    assert "Onyx" not in reset
    assert "Onyx" not in verify
    assert "Onyx" not in body


def test_docs_page_title_is_staffless_ai_backend() -> None:
    app = FastAPI(
        title=f"{ONYX_DEFAULT_APPLICATION_NAME} Backend",
        description=(
            f"{ONYX_DEFAULT_APPLICATION_NAME} API for AI-powered chat with search, "
            "document indexing, agents, actions, and more"
        ),
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    client = TestClient(app)
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    assert spec.json()["info"]["title"] == "StaffLess AI Backend"
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "StaffLess AI Backend" in docs.text
    assert "Onyx Backend" not in docs.text
