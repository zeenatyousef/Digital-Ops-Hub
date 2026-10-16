import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List

from packages.database.session import get_db
from packages.database.models import SocialAccount, User, PublishingJob, Campaign, AuditEvent
from packages.shared_dtos.social_account_dtos import SocialAccountCreate, SocialAccountRead, ManualHandoffRequest
from apps.core_gateway.security import get_current_tenant, RoleChecker
from apps.core_gateway.token_encryption import encrypt_token

router = APIRouter(prefix="/api", tags=["Social Accounts & Queue Settings"])


@router.post("/social-accounts", response_model=SocialAccountRead, status_code=status.HTTP_201_CREATED)
def connect_social_account(
    payload: SocialAccountCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    account = SocialAccount(
        tenant_id=tenant_id,
        platform=payload.platform,
        account_identifier=payload.account_identifier,
        access_token_encrypted=encrypt_token(payload.access_token),
        status="connected"
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/social-accounts", response_model=List[SocialAccountRead])
def list_social_accounts(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    return db.query(SocialAccount).filter(SocialAccount.tenant_id == tenant_id).all()


@router.delete("/social-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_social_account(
    account_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    account = db.query(SocialAccount).filter(SocialAccount.id == account_id, SocialAccount.tenant_id == tenant_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Social account not found")
    db.delete(account)
    db.commit()
    return None


@router.post("/publishing/jobs/{job_id}/manual-handoff", response_model=dict)
def manual_handoff_job(
    job_id: UUID,
    payload: ManualHandoffRequest = None,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    job = db.query(PublishingJob).join(Campaign).filter(PublishingJob.id == job_id, Campaign.tenant_id == tenant_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Publishing job not found")

    proof_str = None
    if payload:
        proof_str = payload.manual_proof or payload.proof_url or payload.proof_note
    if not proof_str:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Manual proof (URL or note) is required to complete manual handoff"
        )

    job.manual_proof = proof_str
    job.status = "manual_handoff"

    campaign = db.query(Campaign).filter(Campaign.id == job.campaign_id).first()
    if campaign:
        remaining_jobs = db.query(PublishingJob).filter(
            PublishingJob.campaign_id == campaign.id,
            PublishingJob.id != job.id,
            PublishingJob.status.in_(["queued", "processing", "failed"])
        ).count()
        if remaining_jobs == 0:
            campaign.status = "published"

    db.add(AuditEvent(
        id=UUID(bytes=uuid.uuid4().bytes),
        tenant_id=tenant_id,
        user_id=current_user.id,
        action_name="publishing.job.manual_handoff",
        entity_name="PublishingJob",
        entity_id=job.id,
        diff_data=json.dumps({"proof": proof_str, "status": job.status}),
        ip_address="127.0.0.1"
    ))

    db.commit()
    db.refresh(job)
    return {
        "id": str(job.id),
        "status": job.status,
        "manual_proof": job.manual_proof,
        "note": "Marked for manual publishing outside the automated queue — a human must complete this post manually."
    }


@router.post("/publishing/jobs/{job_id}/cancel", response_model=dict)
def cancel_publishing_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    job = db.query(PublishingJob).join(Campaign).filter(PublishingJob.id == job_id, Campaign.tenant_id == tenant_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Publishing job not found")

    if job.status != "queued":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only queued jobs can be cancelled. Current status is '{job.status}'"
        )

    job.status = "cancelled"

    db.add(AuditEvent(
        id=UUID(bytes=uuid.uuid4().bytes),
        tenant_id=tenant_id,
        user_id=current_user.id,
        action_name="publishing.job.cancelled",
        entity_name="PublishingJob",
        entity_id=job.id,
        diff_data=json.dumps({"cancelled_by": str(current_user.id)}),
        ip_address="127.0.0.1"
    ))

    db.commit()
    db.refresh(job)
    return {
        "id": str(job.id),
        "status": job.status,
        "detail": "Job successfully cancelled"
    }