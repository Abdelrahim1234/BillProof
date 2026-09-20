from pydantic import BaseModel, Field

from billproof.services.explain import MAX_QUESTION_CHARS


class ExplainRequest(BaseModel):
    question: str | None = Field(default=None, max_length=MAX_QUESTION_CHARS)


class AskRequest(BaseModel):
    question: str = Field(max_length=MAX_QUESTION_CHARS)


class ExplainResponse(BaseModel):
    answer: str
    model: str
