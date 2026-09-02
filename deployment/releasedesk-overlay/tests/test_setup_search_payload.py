"""Regression: setup-onyx.sh must send index_name on set-new-search-settings.

SearchSettingsCreationRequest requires index_name (str | None). Omitting it
returns HTTP 422. Naming matches onyx.natural_language_processing.search_nlp_models
clean_model_name: danswer_chunk_{model with /.- → _}.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

OVERLAY = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = OVERLAY / "setup-onyx.sh"
JQ_FILTER = OVERLAY / "search-settings-payload.jq"


def index_name_for_model(model: str) -> str:
    """Same convention as clean_model_name + danswer_chunk_ prefix."""
    cleaned = re.sub(r"[/.-]", "_", model).lower()
    return f"danswer_chunk_{cleaned}"


class SearchSettingsPayloadTest(unittest.TestCase):
    def test_script_does_not_delete_index_name(self) -> None:
        for path in (SETUP_SCRIPT, JQ_FILTER):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(
                re.search(r"del\([^)]*index_name", text),
                f"{path.name} must not delete index_name (that caused HTTP 422)",
            )

    def test_filter_sets_danswer_chunk_index_name(self) -> None:
        jq = JQ_FILTER.read_text(encoding="utf-8")
        self.assertIn('danswer_chunk_"', jq)
        self.assertIn('gsub("[/.-]"; "_")', jq)

    def test_default_openai_small_model(self) -> None:
        self.assertEqual(
            index_name_for_model("text-embedding-3-small"),
            "danswer_chunk_text_embedding_3_small",
        )

    def test_slash_prefixed_model_not_nomic_index(self) -> None:
        current_nomic = "danswer_chunk_nomic_ai_nomic_embed_text_v1"
        new_name = index_name_for_model("openai/text-embedding-3-small")
        self.assertEqual(new_name, "danswer_chunk_openai_text_embedding_3_small")
        self.assertNotEqual(new_name, current_nomic)


if __name__ == "__main__":
    unittest.main()
