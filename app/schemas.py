from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class UserProfileUpdate(BaseModel):
    exam_name: str = Field(min_length=1, max_length=100)
    exam_date: str | None = None
    daily_minutes: int = Field(ge=10, le=720)


class UnitUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    body: str | None = Field(default=None, min_length=20)
    status: Literal["draft", "approved", "archived"] | None = None
    objective_type: str | None = Field(default=None, min_length=1, max_length=40)




class UnitSplitRequest(BaseModel):
    split_at: int = Field(ge=1)
    body: str | None = Field(default=None, min_length=40, max_length=200000)
    left_title: str | None = Field(default=None, min_length=1, max_length=160)
    right_title: str | None = Field(default=None, min_length=1, max_length=160)
    left_objective_type: str | None = Field(default=None, min_length=1, max_length=40)
    right_objective_type: str | None = Field(default=None, min_length=1, max_length=40)


class UnitMergeRequest(BaseModel):
    other_unit_id: str = Field(min_length=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    objective_type: str | None = Field(default=None, min_length=1, max_length=40)


class StartSessionRequest(BaseModel):
    approve_unit: bool = True


class HintRequest(BaseModel):
    level: int = Field(ge=1, le=2)


class AttemptCreate(BaseModel):
    answer_text: str = Field(min_length=1, max_length=30000)
    confidence: int = Field(ge=0, le=100)
    elapsed_ms: int = Field(ge=0, le=24 * 60 * 60 * 1000)


class Feedback(BaseModel):
    score: float = Field(ge=0, le=100)
    matched_points: list[str]
    missing_points: list[str]
    incorrect_points: list[str]
    expression_issues: list[str]
    next_action: str
    evidence: list[dict[str, Any]]
    provider_note: str
    warning: str | None = None


class DraftUpdate(BaseModel):
    text: str = Field(default="", max_length=30000)
    confidence: int = Field(default=70, ge=0, le=100)


RetrievalItemType = Literal["flashcard", "cloze"]
RetrievalRating = Literal["again", "hard", "good", "easy"]


class RetrievalGenerateRequest(BaseModel):
    item_types: list[RetrievalItemType] = Field(default_factory=lambda: ["flashcard", "cloze"], min_length=1)
    max_per_type: int = Field(default=3, ge=1, le=10)


class RetrievalItemCreate(BaseModel):
    item_type: RetrievalItemType
    prompt: str = Field(min_length=2, max_length=3000)
    answer: str = Field(min_length=1, max_length=10000)
    cloze_text: str | None = Field(default=None, max_length=3000)
    source_excerpt: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def validate_cloze(self) -> "RetrievalItemCreate":
        if self.item_type == "cloze":
            if not self.cloze_text:
                raise ValueError("挖空题必须提供 cloze_text")
            if self.cloze_text.count("____") != 1:
                raise ValueError("挖空题必须且只能包含一个 ____ 空位")
        elif self.cloze_text is not None:
            raise ValueError("闪卡不应提供 cloze_text")
        return self


class RetrievalItemUpdate(BaseModel):
    prompt: str | None = Field(default=None, min_length=2, max_length=3000)
    answer: str | None = Field(default=None, min_length=1, max_length=10000)
    cloze_text: str | None = Field(default=None, max_length=3000)
    source_excerpt: str | None = Field(default=None, min_length=1, max_length=10000)
    status: Literal["active", "archived"] | None = None

    @model_validator(mode="after")
    def validate_cloze_text(self) -> "RetrievalItemUpdate":
        if self.cloze_text is not None and self.cloze_text.count("____") != 1:
            raise ValueError("挖空题必须且只能包含一个 ____ 空位")
        return self


class RetrievalAttemptCreate(BaseModel):
    response_text: str = Field(default="", max_length=10000)
    rating: RetrievalRating | None = None
    elapsed_ms: int = Field(default=0, ge=0, le=24 * 60 * 60 * 1000)
    revealed_answer: bool = False


class PortableStudyDevice(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    label: str = Field(default="portable", max_length=120)
    client: str = Field(default="portable-reviewer/0.1", max_length=120)


class PortableStudyAttemptEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=120)
    event_type: Literal["retrieval_attempt"] = "retrieval_attempt"
    item_id: str = Field(min_length=1, max_length=120)
    item_version: int = Field(ge=1)
    content_hash: str = Field(min_length=8, max_length=128)
    base_last_attempt_id: str | None = Field(default=None, max_length=120)
    occurred_at: datetime
    response_text: str = Field(default="", max_length=10000)
    rating: RetrievalRating | None = None
    elapsed_ms: int = Field(default=0, ge=0, le=24 * 60 * 60 * 1000)
    revealed_answer: bool = False


class PortableStudyEventsImport(BaseModel):
    protocol: Literal["study-events/0.1"]
    bundle_id: str = Field(min_length=1, max_length=120)
    pack_id: str = Field(min_length=1, max_length=120)
    pack_hash: str = Field(min_length=8, max_length=128)
    exported_at: datetime
    device: PortableStudyDevice
    events: list[PortableStudyAttemptEvent] = Field(min_length=1, max_length=1000)
