"""OpenAPI titles on /docs use the StaffLess AI display name."""

import pytest

from onyx.configs.constants import ONYX_DEFAULT_APPLICATION_NAME
from onyx.mcp_server.api import create_mcp_fastapi_app

import onyx.main as onyx_main


def test_api_openapi_title_is_staffless_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onyx_main, "ENABLE_PUBLIC_DOCS", True)
    app = onyx_main.get_application()
    expected = f"{ONYX_DEFAULT_APPLICATION_NAME} Backend"
    assert app.title == expected
    assert "Onyx" not in app.title

    schema = app.openapi()
    assert schema["info"]["title"] == expected
    assert "Onyx" not in schema["info"]["title"]
    assert "Onyx" not in schema["info"]["description"]


def test_mcp_openapi_title_is_staffless_ai() -> None:
    app = create_mcp_fastapi_app()
    expected = f"{ONYX_DEFAULT_APPLICATION_NAME} MCP Server"
    assert app.title == expected
    assert app.openapi()["info"]["title"] == expected
