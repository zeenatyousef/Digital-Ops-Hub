from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from uuid import UUID
import uuid
from datetime import datetime
from typing import List, Optional

from packages.database.session import get_db
from packages.database.models import Campaign, ContentVersion, PublishingJob, User
from packages.shared_dtos.campaign_dtos import (
    CampaignCreate,
    CampaignRead,
    ContentVersionRead,
    PublishingJobRead
)
from apps.core_gateway.security import (
    get_current_tenant,
    RoleChecker
)

router = APIRouter(prefix="/api", tags=["Campaigns & Marketing"])

@router.post("/campaigns", response_model=CampaignRead)
def create_campaign(
    campaign_in: CampaignCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    # Enforce transactional creation of Campaign and ContentVersion
    campaign = Campaign(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        client_id=campaign_in.client_id,
        name=campaign_in.name,
        status="draft",
        scheduled_publish_at=campaign_in.scheduled_publish_at
    )
    db.add(campaign)
    
    # Create first ContentVersion
    first_version = ContentVersion(
        id=uuid.uuid4(),
        campaign_id=campaign.id,
        version_number=1,
        ai_output="AI generated draft caption placeholder.",
        edited_content=campaign_in.caption or "Draft caption text",
        status="pending",
        platform=campaign_in.platform or "LinkedIn",
        language=campaign_in.language or "English",
        caption=campaign_in.caption or "Draft caption text",
        cta=campaign_in.cta or "",
        hashtags_reference=campaign_in.hashtags_reference or ""
    )
    db.add(first_version)
    
    try:
        db.commit()
        db.refresh(campaign)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database transaction failed: {str(e)}")
    
    # Reload with versions loaded
    return db.query(Campaign).options(joinedload(Campaign.versions)).filter(Campaign.id == campaign.id).first()

@router.get("/campaigns", response_model=List[CampaignRead])
def list_campaigns(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer", "client_rep"]))
):
    return db.query(Campaign).options(joinedload(Campaign.versions)).filter(Campaign.tenant_id == tenant_id).all()

@router.get("/campaigns/{campaign_id}", response_model=CampaignRead)
def get_campaign(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer", "client_rep"]))
):
    campaign = db.query(Campaign).options(joinedload(Campaign.versions)).filter(
        Campaign.id == campaign_id,
        Campaign.tenant_id == tenant_id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign

# --- APPROVAL WORKFLOW ENDPOINTS ---

@router.post("/campaigns/{campaign_id}/submit", response_model=CampaignRead)
def submit_campaign_for_approval(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    campaign.status = "pending_approval"
    db.commit()
    
    return db.query(Campaign).options(joinedload(Campaign.versions)).filter(Campaign.id == campaign_id).first()

@router.post("/campaigns/{campaign_id}/approve", response_model=CampaignRead)
def approve_campaign(
    campaign_id: UUID,
    version_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "client_rep"]))
):
    campaign = db.query(Campaign).options(joinedload(Campaign.versions)).filter(
        Campaign.id == campaign_id,
        Campaign.tenant_id == tenant_id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    # Find active/requested version to approve
    version = None
    if version_id:
        version = next((v for v in campaign.versions if v.id == version_id), None)
    elif campaign.versions:
        # Default to the latest version
        version = max(campaign.versions, key=lambda v: v.version_number)
        
    if not version:
        raise HTTPException(status_code=404, detail="Content version not found")
        
    version.status = "approved"
    campaign.status = "approved"
    
    db.commit()
    return campaign

@router.post("/campaigns/{campaign_id}/reject", response_model=CampaignRead)
def reject_campaign(
    campaign_id: UUID,
    version_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "client_rep"]))
):
    campaign = db.query(Campaign).options(joinedload(Campaign.versions)).filter(
        Campaign.id == campaign_id,
        Campaign.tenant_id == tenant_id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    version = None
    if version_id:
        version = next((v for v in campaign.versions if v.id == version_id), None)
    elif campaign.versions:
        version = max(campaign.versions, key=lambda v: v.version_number)
        
    if not version:
        raise HTTPException(status_code=404, detail="Content version not found")
        
    version.status = "rejected"
    campaign.status = "draft" # Reset to draft for revisions
    
    db.commit()
    return campaign

@router.post("/content-versions/{version_id}/approve", response_model=ContentVersionRead)
def approve_content_version(
    version_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "client_rep"]))
):
    version = (
        db.query(ContentVersion)
        .join(Campaign, Campaign.id == ContentVersion.campaign_id)
        .filter(ContentVersion.id == version_id, Campaign.tenant_id == tenant_id)
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Content version not found")

    version.status = "approved"
    version.approved_by_id = current_user.id
    db.commit()
    db.refresh(version)
    return version


@router.post("/content-versions/{version_id}/reject", response_model=ContentVersionRead)
def reject_content_version(
    version_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "client_rep"]))
):
    version = (
        db.query(ContentVersion)
        .join(Campaign, Campaign.id == ContentVersion.campaign_id)
        .filter(ContentVersion.id == version_id, Campaign.tenant_id == tenant_id)
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Content version not found")

    version.status = "rejected"
    db.commit()
    db.refresh(version)
    return version   

# --- PUBLISHING ENFORCEMENT & JOBS ---

@router.post("/campaigns/{campaign_id}/schedule", response_model=PublishingJobRead)
def schedule_publishing(
    campaign_id: UUID,
    scheduled_at: Optional[datetime] = None,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.tenant_id == tenant_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    # Rule: Enforce required approval before scheduling
    if campaign.status != "approved":
        raise HTTPException(status_code=400, detail="Campaign must be approved before scheduling")
        
    pub_time = scheduled_at or campaign.scheduled_publish_at or datetime.utcnow()
    
    # Rule: Idempotency key prevents duplicate publish
    # Formatting idempotency key as campaign_id + date string to prevent duplicate scheduled publications
    idempotency_key = f"pub-{campaign.id}-{pub_time.strftime('%Y%m%d%H%M')}"
    
    # Check if duplicate job exists
    existing_job = db.query(PublishingJob).filter(PublishingJob.idempotency_key == idempotency_key).first()
    if existing_job:
        return existing_job
        
    job = PublishingJob(
        id=uuid.uuid4(),
        campaign_id=campaign.id,
        status="queued",
        idempotency_key=idempotency_key,
        retry_count=0,
        scheduled_at=pub_time
    )
    db.add(job)
    
    campaign.status = "scheduled"
    campaign.scheduled_publish_at = pub_time
    
    db.commit()
    db.refresh(job)
    return job

@router.get("/publishing/jobs", response_model=List[PublishingJobRead])
def list_publishing_jobs(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    return db.query(PublishingJob).join(Campaign).filter(Campaign.tenant_id == tenant_id).all()

@router.post("/publishing/jobs/{job_id}/retry", response_model=PublishingJobRead)
def retry_publishing_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    job = db.query(PublishingJob).join(Campaign).filter(
        PublishingJob.id == job_id,
        Campaign.tenant_id == tenant_id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Publishing job not found")
        
    job.status = "queued"
    job.retry_count += 1
    job.error_logs = None
    
    db.commit()
    db.refresh(job)
    return job
