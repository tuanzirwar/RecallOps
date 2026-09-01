from typing import Literal
from pydantic import BaseModel, Field, HttpUrl


class Message(BaseModel):
    message_id: str
    content: str
    source_url: str


class DraftCreate(BaseModel):
    thread_id: str
    messages: list[Message] = Field(min_length=1)


class CommitRequest(BaseModel):
    draft_id: str
    corrections: dict[str, object] = Field(default_factory=dict)
    confirm: bool


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    service_names: list[str] = Field(default_factory=list)
    error_codes: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)
    mode: Literal["fts", "vector", "hybrid"] = "hybrid"


class CorrectionRequest(BaseModel):
    field: Literal["title", "symptom", "root_cause", "resolution", "severity", "status"]
    new_value: str
    reason: str = Field(min_length=3)


class BootstrapRequest(BaseModel):
    tenant_id: str = "tenant-demo"
    tenant_name: str = "Demo Tenant"
    workspace_id: str = "workspace-demo"
    workspace_name: str = "研发故障空间"
    chat_id: str = "oc_demo"
    user_open_id: str = "ou_maintainer"
    role: Literal["viewer", "member", "maintainer", "admin"] = "maintainer"
