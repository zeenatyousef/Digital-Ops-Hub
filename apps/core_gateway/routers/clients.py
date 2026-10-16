from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID
from typing import List

from packages.database.session import get_db
from packages.database.models import Client, User, Campaign
from packages.shared_dtos.client_dtos import ClientCreate, ClientRead, ClientDetailRead
from apps.core_gateway.security import get_current_tenant, RoleChecker

router = APIRouter(prefix="/api", tags=["Clients"])


@router.post("/clients", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
def create_client(
    payload: ClientCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    existing = db.query(Client).filter(
        Client.tenant_id == tenant_id,
        Client.contact_email == payload.contact_email
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A client with email '{payload.contact_email}' already exists."
        )

    client = Client(
        tenant_id=tenant_id,
        company_name=payload.company_name,
        industry=payload.industry,
        contact_email=payload.contact_email
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.get("/clients", response_model=List[ClientRead])
def list_clients(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer", "client_rep"]))
):
    return db.query(Client).filter(Client.tenant_id == tenant_id).all()


@router.get("/clients/{client_id}", response_model=ClientDetailRead)
def get_client(
    client_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer", "client_rep"]))
):
    client = db.query(Client).filter(Client.id == client_id, Client.tenant_id == tenant_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    campaigns = db.query(Campaign).filter(Campaign.client_id == client_id, Campaign.tenant_id == tenant_id).all()
    team_members = db.query(User).filter(User.client_id == client_id, User.tenant_id == tenant_id).all()

    return ClientDetailRead(
        **{k: getattr(client, k) for k in ["id", "tenant_id", "company_name", "industry", "contact_email", "created_at"]},
        campaigns=campaigns,
        team_members=team_members
    )


@router.patch("/clients/{client_id}", response_model=ClientRead)
def update_client(
    client_id: UUID,
    payload: ClientCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    client = db.query(Client).filter(Client.id == client_id, Client.tenant_id == tenant_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if payload.contact_email != client.contact_email:
        existing = db.query(Client).filter(
            Client.tenant_id == tenant_id,
            Client.contact_email == payload.contact_email,
            Client.id != client_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A client with email '{payload.contact_email}' already exists."
            )

    client.company_name = payload.company_name
    client.industry = payload.industry
    client.contact_email = payload.contact_email
    db.commit()
    db.refresh(client)
    return client


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(
    client_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    client = db.query(Client).filter(Client.id == client_id, Client.tenant_id == tenant_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    db.delete(client)
    db.commit()
    return None