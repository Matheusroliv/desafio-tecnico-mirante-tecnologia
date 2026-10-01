from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_CHARS = 1_048_576


class ModernizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_code: str = Field(min_length=1, max_length=MAX_CHARS)
    schema_ddl: str | None = Field(default=None, max_length=MAX_CHARS)

    @field_validator("source_code")
    @classmethod
    def source_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_code vazio")
        return value


class ModernizeResponse(BaseModel):
    id: int
    status: str
    generated_code: str | None
    report: dict
