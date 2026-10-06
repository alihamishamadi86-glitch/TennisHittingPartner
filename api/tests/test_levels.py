from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.services.levels import QUESTIONS, suggest_ntrp


def answers(value: int, **overrides: int) -> dict[str, int]:
    return {q.key: value for q in QUESTIONS} | overrides


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (answers(0), Decimal("1.5")),
        (answers(3), Decimal("5.5")),
        (answers(2), Decimal("4.0")),
        (answers(1), Decimal("3.0")),
        (answers(3, competition=1), Decimal("4.0")),  # capped without competitive experience
        (answers(2, competition=3, serve=3, rally=3), Decimal("5.0")),
    ],
)
def test_suggest_ntrp(given: dict[str, int], expected: Decimal) -> None:
    assert suggest_ntrp(given) == expected


def test_suggestions_are_half_steps_within_self_assessment_range() -> None:
    for value in range(4):
        for competition in range(4):
            rating = suggest_ntrp(answers(value, competition=competition))
            assert Decimal("1.5") <= rating <= Decimal("5.5")
            assert (rating * 2) % 1 == 0


async def test_questionnaire_endpoint(api_client: AsyncClient) -> None:
    body = (await api_client.get("/levels/questionnaire")).json()
    assert [q["key"] for q in body["questions"]] == [q.key for q in QUESTIONS]
    assert all(len(q["options"]) == 4 for q in body["questions"])


async def test_suggest_endpoint(api_client: AsyncClient) -> None:
    response = await api_client.post("/levels/suggest", json=answers(2))
    assert response.status_code == 200
    assert response.json()["ntrp_rating"] == 4.0
    assert response.json()["description"]


async def test_suggest_rejects_out_of_range_answers(api_client: AsyncClient) -> None:
    assert (await api_client.post("/levels/suggest", json=answers(4))).status_code == 422
