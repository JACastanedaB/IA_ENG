from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator

Category = Literal["billing", "technical", "account", "other"]

class TriageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)
    category: Category
    actions: list[str] = Field(min_length=1, max_length=8)

    @field_validator("actions")
    @classmethod
    def validate_actions(cls, actions: list[str]) -> list[str]:
        cleaned = [a.strip() for a in actions if a.strip()]
        if not cleaned:
            raise ValueError("actions must contain at least one non-empty item")
        return cleaned
