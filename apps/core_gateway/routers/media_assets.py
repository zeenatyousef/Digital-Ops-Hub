from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Optional

from packages.database.session import get_db
from packages.database.models import MediaAsset, User
from packages.shared_dtos.media_dtos import MediaAssetCreate, MediaAssetRead
from apps.core_gateway.security import get_current_tenant, RoleChecker

router = APIRouter(prefix="/api", tags=["Media Assets"])


@router.post("/media-assets", response_model=MediaAssetRead, status_code=status.HTTP_201_CREATED)
def create_media_asset(
    payload: MediaAssetCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    # Auto-increment version number for this campaign
    last_version = (
        db.query(MediaAsset)
        .filter(MediaAsset.tenant_id == tenant_id, MediaAsset.campaign_id == payload.campaign_id)
        .order_by(MediaAsset.version_number.desc())
        .first()
    )
    next_version = (last_version.version_number + 1) if last_version else 1

    asset = MediaAsset(
        tenant_id=tenant_id,
        campaign_id=payload.campaign_id,
        file_url=payload.file_url,
        version_number=next_version
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/media-assets", response_model=List[MediaAssetRead])
def list_media_assets(
    campaign_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer", "client_rep"]))
):
    query = db.query(MediaAsset).filter(MediaAsset.tenant_id == tenant_id)
    if campaign_id:
        query = query.filter(MediaAsset.campaign_id == campaign_id)
    return query.order_by(MediaAsset.version_number.asc()).all()


@router.post("/media-assets/{asset_id}/approve", response_model=MediaAssetRead)
def approve_media_asset(
    asset_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "client_rep"]))
):
    asset = db.query(MediaAsset).filter(MediaAsset.id == asset_id, MediaAsset.tenant_id == tenant_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")

    asset.status = "approved"
    asset.is_locked = True
    asset.reviewed_by_id = current_user.id
    db.commit()
    db.refresh(asset)
    return asset