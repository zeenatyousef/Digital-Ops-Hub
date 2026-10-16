from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from uuid import UUID
import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

from packages.database.session import get_db
from packages.database.models import KBArticle, User, AuditEvent
from packages.shared_dtos.support_dtos import KBArticleRead
from apps.core_gateway.security import (
    get_current_tenant,
    get_current_active_user,
    RoleChecker
)

router = APIRouter(prefix="/api", tags=["Knowledge Base Articles"])

class KBArticleCreateRequest(BaseModel):
    title: str
    content: str
    product: Optional[str] = None
    risk_level: Optional[str] = None

def log_audit_event(db: Session, tenant_id: UUID, user_id: UUID, action: str, entity: str, entity_id: UUID, diff: str = None):
    audit = AuditEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        action_name=action,
        entity_name=entity,
        entity_id=entity_id,
        diff_data=diff,
        created_at=datetime.utcnow()
    )
    db.add(audit)

@router.post("/kb-articles", response_model=KBArticleRead, status_code=status.HTTP_201_CREATED)
def create_kb_article(
    req: KBArticleCreateRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    """
    Create a new KB article. Always created with review_status = 'draft'.
    tenant_id is resolved from authentication token, never trusted from client request body.
    """
    article_id = uuid.uuid4()
    article = KBArticle(
        id=article_id,
        tenant_id=tenant_id,
        title=req.title,
        content=req.content,
        review_status="draft",
        product=req.product,
        risk_level=req.risk_level,
        created_at=datetime.utcnow()
    )
    db.add(article)

    log_audit_event(
        db, tenant_id, current_user.id, "create_kb_article", "KBArticle", article_id,
        diff=f"title: {req.title}, review_status: draft"
    )

    try:
        db.commit()
        db.refresh(article)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error during KB article creation: {str(e)}")

    return article

@router.get("/kb-articles", response_model=List[KBArticleRead])
def list_kb_articles(
    review_status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user)
):
    """
    List KB articles for the caller's tenant.
    """
    query = db.query(KBArticle).filter(KBArticle.tenant_id == tenant_id)
    if review_status:
        query = query.filter(KBArticle.review_status == review_status)
    return query.order_by(KBArticle.created_at.desc()).all()

@router.post("/kb-articles/{article_id}/approve", response_model=KBArticleRead)
def approve_kb_article(
    article_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    """
    Approve a draft KB article.
    """
    article = db.query(KBArticle).filter(
        KBArticle.id == article_id,
        KBArticle.tenant_id == tenant_id
    ).first()

    if not article:
        raise HTTPException(status_code=404, detail="KB article not found")

    old_status = article.review_status
    article.review_status = "approved"

    log_audit_event(
        db, tenant_id, current_user.id, "approve_kb_article", "KBArticle", article_id,
        diff=f"status: {old_status} -> approved"
    )

    try:
        db.commit()
        db.refresh(article)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error approving KB article: {str(e)}")

    return article
