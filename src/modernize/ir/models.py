from typing import Literal

from pydantic import BaseModel, Field


class Parameter(BaseModel):
    name: str
    mode: Literal["in", "out", "inout"]
    type_name: str


class Variable(BaseModel):
    name: str
    type_name: str


class SqlStmt(BaseModel):
    sql: str
    into: bool = False
    into_targets: list[str] = Field(default_factory=list)
    in_loop: bool = False
    in_exception: bool = False
    cursor: bool = False


class RaiseStmt(BaseModel):
    level: int
    message: str | None = None
    in_exception: bool = False


class Operation(BaseModel):
    kind: Literal["select", "insert", "update", "delete", "return"]
    count: int


class Risk(BaseModel):
    id: str
    detail: str


class RoutineIR(BaseModel):
    name: str
    kind: Literal["function", "procedure"]
    parameters: list[Parameter]
    return_columns: list[Parameter] = Field(default_factory=list)
    returns: str | None
    set_returning: bool
    language: str
    variables: list[Variable] = Field(default_factory=list)
    statements: list[SqlStmt] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    raises: list[RaiseStmt] = Field(default_factory=list)
    assigns: list[str] = Field(default_factory=list)
    return_queries: list[str] = Field(default_factory=list)
    has_get_diagnostics: bool = False
    has_loop: bool = False
    has_cursor: bool = False
    has_exception: bool = False
    exception_reraises: bool = False
    exception_has_insert: bool = False
    constructs: list[str] = Field(default_factory=list)
    operations: list[Operation] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
