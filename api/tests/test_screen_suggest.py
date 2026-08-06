from typing import Any

import pytest

from services import gene_wiki_aaron
from services.execution import blocking_target


def test_screen_suggestions_only_query_comparable_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_fetch(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        captured["sql"] = sql
        captured["params"] = params
        return [
            {
                "screen_id": "2123",
                "cell_line": "KMS-12-BM",
                "condition_name": "",
                "phenotype": "fitness",
                "author": "Behan",
                "pmid": "30971826",
                "number_of_hits": "101",
            }
        ]

    monkeypatch.setattr(gene_wiki_aaron, "db_fetchall", fake_fetch)
    suggest = blocking_target(gene_wiki_aaron.get_screen_suggest)

    result = suggest("KMS12", 9606, 8)

    assert "JOIN screen_sim_meta" in captured["sql"]
    assert "k.taxid = ?" in captured["sql"]
    assert captured["params"][0] == 9606
    assert result[0]["screen_id"] == "2123"


def test_empty_screen_suggestion_skips_database(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_fetch(_sql: str, _params: tuple = ()) -> list[dict[str, Any]]:
        raise AssertionError("empty suggestions must not query the database")

    monkeypatch.setattr(gene_wiki_aaron, "db_fetchall", unexpected_fetch)
    suggest = blocking_target(gene_wiki_aaron.get_screen_suggest)

    assert suggest("", 9606, 8) == []
