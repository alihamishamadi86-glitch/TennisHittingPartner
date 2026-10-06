from fastapi import APIRouter

from app.schemas.profiles import (
    LevelAnswersIn,
    LevelSuggestionOut,
    QuestionnaireOut,
    QuestionOut,
)
from app.services import levels

router = APIRouter(prefix="/levels", tags=["levels"])


@router.get("/questionnaire")
async def questionnaire() -> QuestionnaireOut:
    return QuestionnaireOut(
        questions=[
            QuestionOut(key=q.key, prompt=q.prompt, options=list(q.options))
            for q in levels.QUESTIONS
        ]
    )


@router.post("/suggest")
async def suggest(body: LevelAnswersIn) -> LevelSuggestionOut:
    rating = levels.suggest_ntrp(body.model_dump())
    return LevelSuggestionOut(ntrp_rating=rating, description=levels.describe(rating))
