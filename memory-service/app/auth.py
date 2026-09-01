from dataclasses import dataclass
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session
from .config import get_settings
from .database import get_db
from .models import Workspace, WorkspaceMember


ROLE_LEVEL = {"viewer": 1, "member": 2, "maintainer": 3, "admin": 4}


@dataclass(frozen=True)
class Identity:
    tenant_id: str
    workspace_id: str
    user_id: str
    role: str


def identity(
    x_proxy_token: str = Header(...),
    x_tenant_id: str = Header(...),
    x_workspace_id: str = Header(...),
    x_user_id: str = Header(...),
    db: Session = Depends(get_db),
) -> Identity:
    if x_proxy_token != get_settings().trusted_proxy_token:
        raise HTTPException(401, "untrusted caller")
    ws = db.get(Workspace, x_workspace_id)
    member = db.get(WorkspaceMember, (x_workspace_id, x_user_id))
    if not ws or ws.tenant_id != x_tenant_id or not member:
        raise HTTPException(403, "workspace access denied")
    return Identity(x_tenant_id, x_workspace_id, x_user_id, member.role)


def require(subject: Identity, minimum: str) -> None:
    if ROLE_LEVEL.get(subject.role, 0) < ROLE_LEVEL[minimum]:
        raise HTTPException(403, f"{minimum} role required")

