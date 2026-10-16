from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID
import uuid
from datetime import datetime
from typing import List, Optional

from packages.database.session import get_db
from packages.database.models import BrandProfile, CampaignBrief, CalendarItem, Campaign, AuditEvent, User, DesignerBrief
from apps.core_gateway.security import (
    get_current_tenant,
    get_current_active_user,
    RoleChecker
)

router = APIRouter(prefix="/api", tags=["Marketing Workflows & Calendar"])

# Helper to log audit event
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

# --- BRAND PROFILES ---

@router.post("/brand-profiles", status_code=status.HTTP_201_CREATED)
def create_brand_profile(
    brand_name: str,
    client_id: UUID,
    brand_voice: Optional[str] = None,
    target_audience: Optional[str] = None,
    required_wording: Optional[str] = None,
    prohibited_wording: Optional[str] = None,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    profile = BrandProfile(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        client_id=client_id,
        brand_name=brand_name,
        brand_voice=brand_voice,
        target_audience=target_audience,
        required_wording=required_wording,
        prohibited_wording=prohibited_wording,
        version_number=1,
        created_at=datetime.utcnow()
    )
    db.add(profile)
    
    log_audit_event(db, tenant_id, current_user.id, "create_brand_profile", "BrandProfile", profile.id)
    
    try:
        db.commit()
        db.refresh(profile)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    return profile

@router.get("/brand-profiles", response_model=List[dict])
def list_brand_profiles(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user)
):
    profiles = db.query(BrandProfile).filter(BrandProfile.tenant_id == tenant_id).all()
    return [
        {
            "id": str(p.id),
            "client_id": str(p.client_id),
            "brand_name": p.brand_name,
            "brand_voice": p.brand_voice,
            "target_audience": p.target_audience,
            "required_wording": p.required_wording,
            "prohibited_wording": p.prohibited_wording,
            "version_number": p.version_number
        }
        for p in profiles
    ]

# --- CALENDAR RECORDS & WORKFLOWS ---

@router.get("/calendar", response_model=List[dict])
def list_calendar_items(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user)
):
    items = db.query(CalendarItem).filter(CalendarItem.tenant_id == tenant_id).all()
    return [
        {
            "id": str(i.id),
            "campaign_brief_id": str(i.campaign_brief_id) if i.campaign_brief_id else None,
            "scheduled_time": i.scheduled_time.isoformat(),
            "content_draft": i.content_draft,
            "platform": i.platform,
            "objective": i.objective,
            "status": i.status,
            "owner": i.owner
        }
        for i in items
    ]

@router.post("/calendar", status_code=status.HTTP_201_CREATED)
def create_calendar_item(
    scheduled_time: datetime,
    platform: str,
    content_draft: Optional[str] = None,
    objective: Optional[str] = None,
    campaign_brief_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    item = CalendarItem(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        campaign_brief_id=campaign_brief_id,
        scheduled_time=scheduled_time,
        content_draft=content_draft,
        platform=platform,
        objective=objective,
        status="planned",
        owner=current_user.full_name,
        created_at=datetime.utcnow()
    )
    db.add(item)
    
    log_audit_event(db, tenant_id, current_user.id, "create_calendar_item", "CalendarItem", item.id)
    
    try:
        db.commit()
        db.refresh(item)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    return {
        "id": str(item.id),
        "scheduled_time": item.scheduled_time.isoformat(),
        "platform": item.platform,
        "content_draft": item.content_draft,
        "status": item.status,
        "owner": item.owner
    }

@router.post("/campaigns/{campaign_id}/calendar", status_code=status.HTTP_201_CREATED)
def persist_campaign_to_calendar(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    # Retrieve approved campaign
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.tenant_id == tenant_id
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    # Persist as CalendarItem
    item = CalendarItem(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        scheduled_time=campaign.scheduled_publish_at or datetime.utcnow(),
        content_draft=f"Campaign: {campaign.name}",
        platform="Multi-channel",
        objective="Campaign persist workflow",
        status="scheduled",
        owner=current_user.full_name,
        created_at=datetime.utcnow()
    )
    db.add(item)
    
    log_audit_event(db, tenant_id, current_user.id, "persist_campaign_to_calendar", "CalendarItem", item.id)
    
    try:
        db.commit()
        db.refresh(item)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        
    return {
        "status": "persisted",
        "calendar_item_id": str(item.id),
        "scheduled_time": item.scheduled_time.isoformat()
    }

# --- CAMPAIGN BRIEFS ---

@router.get("/campaign-briefs", response_model=List[dict])
def list_campaign_briefs(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user)
):
    briefs = db.query(CampaignBrief).filter(CampaignBrief.tenant_id == tenant_id).all()
    return [
        {
            "id": str(b.id),
            "brand_profile_id": str(b.brand_profile_id),
            "title": b.title,
            "audience": b.audience,
            "location": b.location,
            "offer": b.offer,
            "dates": b.dates,
            "deliverables": b.deliverables,
            "platforms": b.platforms,
            "assets": b.assets,
            "approval_status": b.approval_status,
            "missing_fields": b.missing_fields
        }
        for b in briefs
    ]

@router.post("/campaign-briefs/{brief_id}/approve", response_model=dict)
def approve_campaign_brief(
    brief_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    brief = db.query(CampaignBrief).filter(
        CampaignBrief.id == brief_id,
        CampaignBrief.tenant_id == tenant_id
    ).first()
    if not brief:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign brief not found")
    
    brief.approval_status = "approved"
    log_audit_event(db, tenant_id, current_user.id, "approve_campaign_brief", "CampaignBrief", brief.id)
    
    try:
        db.commit()
        db.refresh(brief)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {str(e)}")
    
    return {"status": "approved", "campaign_brief_id": str(brief.id)}


# --- DESIGNER BRIEFS ---

@router.get("/designer-briefs", response_model=List[dict])
def list_designer_briefs(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user)
):
    briefs = db.query(DesignerBrief).filter(DesignerBrief.tenant_id == tenant_id).all()
    return [
        {
            "id": str(b.id),
            "campaign_id": str(b.campaign_id) if b.campaign_id else None,
            "content_version_id": str(b.content_version_id) if b.content_version_id else None,
            "main_heading": b.main_heading,
            "supporting_text": b.supporting_text,
            "cta": b.cta,
            "visual_direction": b.visual_direction,
            "asset_references": b.asset_references,
            "sizes": b.sizes,
            "logo_qr_rules": b.logo_qr_rules,
            "restrictions": b.restrictions,
            "created_at": b.created_at.isoformat() if b.created_at else None
        }
        for b in briefs
    ]

# --- AUDIT LOGS ENDPOINT ---

@router.get("/audit-events", response_model=List[dict])
def list_audit_events(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    events = db.query(AuditEvent).filter(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.created_at.desc()).all()
    return [
        {
            "id": str(e.id),
            "user_id": str(e.user_id) if e.user_id else None,
            "action_name": e.action_name,
            "entity_name": e.entity_name,
            "entity_id": str(e.entity_id) if e.entity_id else None,
            "diff_data": e.diff_data,
            "created_at": e.created_at.isoformat()
        }
        for e in events
    ]
