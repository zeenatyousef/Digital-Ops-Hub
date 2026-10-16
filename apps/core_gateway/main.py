import os
import time
from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from uuid import UUID
import uuid
from contextlib import asynccontextmanager

from packages.database.session import get_db, SessionLocal
from packages.database.models import Tenant, Client, User, ClientRoom, BrandProfile
from apps.core_gateway.routers import campaigns, auth, messaging, marketing, proxy, clients, media_assets, social_accounts, kb_articles
from apps.core_gateway.security import get_password_hash
from apps.core_gateway.scheduler import start_scheduler, stop_scheduler

# Load env variables
load_dotenv()

# Define Lifespan for background worker startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the publishing job scheduler loop
    start_scheduler()
    
    # Auto-seed the database on startup if ALLOW_SEED is enabled
    if os.getenv("ALLOW_SEED", "false").lower() == "true":
        db = SessionLocal()
        try:
            seed_database(db)
            print("[Lifespan] Database auto-seeded successfully on startup.")
        except Exception as e:
            print(f"[Lifespan] Auto-seeding database on startup failed: {e}")
        finally:
            db.close()
        
    yield
    # Stop the scheduler thread cleanly on shutdown
    stop_scheduler()

# Initialize FastAPI application
app = FastAPI(
    title="NW Digital Operations Hub API Gateway",
    description="Core Gateway for managing clients, messaging, workflows, and integrations",
    version="3.0.0",
    lifespan=lifespan
)

# Enable CORS (configurable via CORS_ORIGINS env variable, defaults to allow all)
cors_origins_raw = os.getenv("CORS_ORIGINS", "*")
cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(campaigns.router)
app.include_router(auth.router)
app.include_router(messaging.router)
app.include_router(marketing.router)
app.include_router(proxy.router)
app.include_router(clients.router)
app.include_router(media_assets.router)
app.include_router(social_accounts.router)
app.include_router(kb_articles.router)

# Custom logging and correlation middleware
@app.middleware("http")
async def add_process_time_and_trace_id(request: Request, call_next):
    start_time = time.time()
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(time.time()*1000)}")
    
    # Process request
    response = await call_next(request)
    
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Correlation-ID"] = correlation_id
    return response

# Root endpoint
@app.get("/")
def read_root():
    return {
        "status": "online",
        "service": "NW Digital Operations Hub Gateway",
        "version": "3.0.0",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }

# Healthcheck endpoint
@app.get("/health")
def healthcheck():
    return {
        "status": "healthy",
        "database": "online",
        "redis": "untested"
    }

# Seeding route for developer testing
@app.post("/api/seed")
def seed_database(db: Session = Depends(get_db)):
    if os.getenv("ALLOW_SEED", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="Not Found")

    # 1. Create Tenant
    tenant_id = UUID("00000000-0000-0000-0000-00000000000a")
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        tenant = Tenant(id=tenant_id, name="National Wireless Corp", status="active")
        db.add(tenant)
    
    # 2. Create Clients
    client_id = UUID("00000000-0000-0000-0000-00000000000b")
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        client = Client(
            id=client_id,
            tenant_id=tenant_id,
            company_name="Acme Wireless Partners",
            contact_email="contact@acmewireless.com",
            industry="Telecommunications"
        )
        db.add(client)

    client2_id = UUID("7b535287-e562-4e84-9bc7-886f67915ec2")
    client2 = db.query(Client).filter(Client.id == client2_id).first()
    if not client2:
        client2 = Client(
            id=client2_id,
            tenant_id=tenant_id,
            company_name="Test Client Co",
            contact_email="testclient@acmewireless.com",
            industry="Retail"
        )
        db.add(client2)

    # Seed bebop, samvix, abc-traders
    client_bebop_id = UUID("00000000-0000-0000-0000-0000000000b3")
    client_bebop = db.query(Client).filter(Client.id == client_bebop_id).first()
    if not client_bebop:
        client_bebop = Client(
            id=client_bebop_id,
            tenant_id=tenant_id,
            company_name="Bebop",
            contact_email="contact@bebop.com",
            industry="Technology"
        )
        db.add(client_bebop)

    client_samvix_id = UUID("00000000-0000-0000-0000-0000000000b5")
    client_samvix = db.query(Client).filter(Client.id == client_samvix_id).first()
    if not client_samvix:
        client_samvix = Client(
            id=client_samvix_id,
            tenant_id=tenant_id,
            company_name="Samvix",
            contact_email="contact@samvix.com",
            industry="Manufacturing"
        )
        db.add(client_samvix)

    client_abc_id = UUID("00000000-0000-0000-0000-0000000000b7")
    client_abc = db.query(Client).filter(Client.id == client_abc_id).first()
    if not client_abc:
        client_abc = Client(
            id=client_abc_id,
            tenant_id=tenant_id,
            company_name="ABC Traders",
            contact_email="contact@abctraders.com",
            industry="Logistics"
        )
        db.add(client_abc)

    # 2.5 Create Brand Profiles
    bp1_id = UUID("00000000-0000-0000-0000-0000000000b1")
    bp1 = db.query(BrandProfile).filter(BrandProfile.id == bp1_id).first()
    if not bp1:
        bp1 = BrandProfile(
            id=bp1_id,
            tenant_id=tenant_id,
            client_id=client_id,
            brand_name="Acme Partners",
            brand_voice="Professional, helpful, friendly",
            required_wording="halal",
            prohibited_wording="guaranteed,best in the world"
        )
        db.add(bp1)

    bp2_id = UUID("00000000-0000-0000-0000-0000000000b2")
    bp2 = db.query(BrandProfile).filter(BrandProfile.id == bp2_id).first()
    if not bp2:
        bp2 = BrandProfile(
            id=bp2_id,
            tenant_id=tenant_id,
            client_id=client2_id,
            brand_name="Test Client Brand",
            brand_voice="Creative, friendly",
            required_wording="halal",
            prohibited_wording="guaranteed,best in the world"
        )
        db.add(bp2)

    bp_bebop_id = UUID("00000000-0000-0000-0000-0000000000b4")
    bp_bebop = db.query(BrandProfile).filter(BrandProfile.id == bp_bebop_id).first()
    if not bp_bebop:
        bp_bebop = BrandProfile(
            id=bp_bebop_id,
            tenant_id=tenant_id,
            client_id=client_bebop_id,
            brand_name="Bebop",
            brand_voice="Vibrant, high-tech",
            required_wording="halal",
            prohibited_wording="guaranteed,best in the world"
        )
        db.add(bp_bebop)

    bp_samvix_id = UUID("00000000-0000-0000-0000-0000000000b6")
    bp_samvix = db.query(BrandProfile).filter(BrandProfile.id == bp_samvix_id).first()
    if not bp_samvix:
        bp_samvix = BrandProfile(
            id=bp_samvix_id,
            tenant_id=tenant_id,
            client_id=client_samvix_id,
            brand_name="Samvix",
            brand_voice="Corporate, formal",
            required_wording="halal",
            prohibited_wording="guaranteed,best in the world"
        )
        db.add(bp_samvix)

    bp_abc_id = UUID("00000000-0000-0000-0000-0000000000b8")
    bp_abc = db.query(BrandProfile).filter(BrandProfile.id == bp_abc_id).first()
    if not bp_abc:
        bp_abc = BrandProfile(
            id=bp_abc_id,
            tenant_id=tenant_id,
            client_id=client_abc_id,
            brand_name="ABC Traders",
            brand_voice="Direct, friendly",
            required_wording="halal",
            prohibited_wording="guaranteed,best in the world"
        )
        db.add(bp_abc)
        
    # 3. Create Users for all roles
    seeded_users = [
        {
            "id": UUID("00000000-0000-0000-0000-00000000000c"),
            "email": "atif@nationalwireless.com",
            "full_name": "Atif Zaheer",
            "role": "super_admin"
        },
        {
            "id": UUID("00000000-0000-0000-0000-00000000000d"),
            "email": "admin@nationalwireless.com",
            "full_name": "Tenant Administrator",
            "role": "tenant_admin"
        },
        {
            "id": UUID("00000000-0000-0000-0000-00000000000e"),
            "email": "designer@nationalwireless.com",
            "full_name": "Lead Designer",
            "role": "designer"
        },
        {
            "id": UUID("00000000-0000-0000-0000-00000000000f"),
            "email": "client@acmewireless.com",
            "full_name": "Client Representative",
            "role": "client_rep"
        }
    ]
    
    for u_data in seeded_users:
        user = db.query(User).filter(User.id == u_data["id"]).first()
        if not user:
            user = User(
                id=u_data["id"],
                tenant_id=tenant_id,
                email=u_data["email"],
                password_hash=get_password_hash("password"),
                full_name=u_data["full_name"],
                role=u_data["role"],
                is_active=True
            )
            db.add(user)
            
    # 4. Create default ClientRoom
    room_id = UUID("00000000-0000-0000-0000-0000000000a1")
    room = db.query(ClientRoom).filter(ClientRoom.id == room_id).first()
    if not room:
        room = ClientRoom(
            id=room_id,
            client_id=client_id,
            tenant_id=tenant_id,
            status="active"
        )
        db.add(room)
        
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database seeding failed: {str(e)}")
        
    return {
        "status": "seeded",
        "tenant": {"id": str(tenant_id), "name": "National Wireless Corp"},
        "client": {"id": str(client_id), "company_name": "Acme Wireless Partners"},
        "client_room": {"id": str(room_id)},
        "users": [
            {"email": u["email"], "role": u["role"], "password": "password"}
            for u in seeded_users
        ]
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)
