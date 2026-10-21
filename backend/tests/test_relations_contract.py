"""The relations contract fixture PR 20's mocks import fits the API's models and rules."""

import json
from pathlib import Path

from app.models.relations import RelationDetail, Relations
from app.services.urls import web_url

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "frontend/e2e/relations.contract.json").read_text(
        encoding="utf-8"
    )
)
QUADS = {"verbal_cooperation", "material_cooperation", "verbal_conflict", "material_conflict"}


def test_every_answer_fits_its_model():
    Relations.model_validate(CONTRACT["list"])
    Relations.model_validate(CONTRACT["list_conflict"])
    RelationDetail.model_validate(CONTRACT["detail"])
    assert CONTRACT["not_found"] == {"detail": "No reported events between them in the last 7 days."}


def test_pairs_are_in_code_order_with_every_quad_key_and_no_report_count():
    for answer in (CONTRACT["list"], CONTRACT["list_conflict"]):
        for rel in answer["relations"]:
            assert rel["a"]["iso"] < rel["b"]["iso"]
            assert set(rel["quad"]) == QUADS
            assert "reports" not in rel
            assert rel["n"] == sum(rel["quad"].values())


def test_a_class_filter_zeroes_the_other_class_and_names_itself():
    for rel in CONTRACT["list_conflict"]["relations"]:
        assert rel["kind"] == "conflict"
        assert rel["quad"]["verbal_cooperation"] == rel["quad"]["material_cooperation"] == 0


def test_the_detail_lists_a_to_b_first_and_adds_up():
    detail = CONTRACT["detail"]
    a, b = detail["a"]["iso"], detail["b"]["iso"]
    assert a < b
    assert [(d["from"], d["to"]) for d in detail["directions"]] == [(a, b), (b, a)]
    assert sum(d["n"] for d in detail["directions"]) == detail["n"]
    assert len(detail["daily"]) == 7
    assert sum(d["cooperation"] + d["conflict"] for d in detail["daily"]) == detail["n"]
    assert all(web_url(s["url"]) for s in detail["samples"])
