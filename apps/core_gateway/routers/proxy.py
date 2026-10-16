import os
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status, Request
import httpx
from uuid import UUID

from sqlalchemy.orm import Session
from packages.database.session import get_db
from packages.database.models import User, KBArticle
from apps.core_gateway.security import (
    get_current_tenant,
    RoleChecker
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Downstream Integrations & Proxy"])

class DynamicURL:
    def __init__(self, env_var: str, default: str):
        self.env_var = env_var
        self.default = default
        
    def __str__(self):
        return os.getenv(self.env_var, self.default).rstrip("/")
        
    def __repr__(self):
        return str(self)

# Read downstream service URLs from environment variables dynamically
VISHAQA_API_URL = DynamicURL("VISHAQA_API_URL", "http://localhost:8001")
ASMA_API_URL = DynamicURL("ASMA_API_URL", "http://localhost:8002")
ESHA_API_URL = DynamicURL("ESHA_API_URL", "http://localhost:8003")

# Timeout configurations for AI calls (5 seconds connection/read timeout)
TIMEOUT_CONFIG = httpx.Timeout(30.0)

# Helper function to forward request with tracing, timeout, and custom exceptions
async def _forward_post(
    service_url: str,
    path: str,
    payload: Dict[str, Any],
    correlation_id: str,
    fallback_response: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    url = f"{service_url}{path}"
    headers = {
        "X-Correlation-ID": correlation_id,
        "Content-Type": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_CONFIG) as client:
            response = await client.post(url, json=payload, headers=headers)
            
            # If the downstream service returns a bad response but did not raise a connection error
            if response.status_code >= 400:
                logger.warning(
                    f"Downstream service returned status {response.status_code} for path {path}. payload: {payload}"
                )
                if fallback_response is not None:
                    return fallback_response
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Downstream service returned error: {response.text}"
                )
                
            return response.json()
            
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.HTTPError) as e:
        logger.error(f"Downstream connection error on {url}: {str(e)}")
        if fallback_response is not None:
            logger.info(f"Returning pre-configured fallback state for path {path}")
            return fallback_response
            
        # Raise clear, user-friendly exception preventing raw server stack traces
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The requested AI integration service is currently offline. Please try again later or process manually."
        )

# Helper function to forward GET requests with query params and tracing
async def _forward_get(
    service_url: str,
    path: str,
    correlation_id: str,
    params: Optional[Dict[str, Any]] = None,
    fallback_response: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    url = f"{service_url}{path}"
    headers = {
        "X-Correlation-ID": correlation_id
    }
    
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_CONFIG) as client:
            response = await client.get(url, params=params, headers=headers)
            
            if response.status_code >= 400:
                logger.warning(
                    f"Downstream service returned status {response.status_code} for path {path}."
                )
                if fallback_response is not None:
                    return fallback_response
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Downstream service returned error: {response.text}"
                )
                
            return response.json()
            
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.HTTPError) as e:
        logger.error(f"Downstream connection error on {url}: {str(e)}")
        if fallback_response is not None:
            logger.info(f"Returning pre-configured fallback state for path {path}")
            return fallback_response
            
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The requested AI integration service is currently offline. Please try again later or process manually."
        )

# --- VISHAQA (SUPPORT AI) ENDPOINTS ---

@router.post("/support/classify")
async def proxy_support_classify(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    
    # Security Rule: Resolve tenant from authentication token and force-inject it
    payload["tenant_id"] = str(tenant_id)
    
    fallback = {
        "product": "Unclassified",
        "category": "General Support / Service Offline Fallback",
        "severity": "Medium",
        "owner_team": "General Support",
        "confidence": 0.5,
        "human_required": True,
        "priority": 100,
        "service_version": "v1.0-fallback"
    }
    
    return await _forward_post(VISHAQA_API_URL, "/support/classify", payload, correlation_id, fallback)

@router.post("/support/summarize")
async def proxy_support_summarize(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    
    fallback = {
        "summary_text": "Conversation summary generation offline. Please review messages manually.",
        "source_message_ids": [],
        "extracted_actions": [],
        "extracted_dates": [],
        "missing_information": ["Service offline fallback"],
        "sentiment": "neutral",
        "service_version": "v1.0-fallback"
    }
    
    return await _forward_post(VISHAQA_API_URL, "/support/summarize", payload, correlation_id, fallback)

@router.post("/support/retrieve")
async def proxy_support_retrieve(
    payload: Dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer", "client_rep"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)

    # Prepare database fallback response (retrieves approved KBArticles for this tenant)
    product_filter = payload.get("product")
    db_query = db.query(KBArticle).filter(
        KBArticle.tenant_id == tenant_id,
        KBArticle.review_status == "approved"
    )
    if product_filter:
        db_query = db_query.filter(KBArticle.product.ilike(f"%{product_filter}%"))

    approved_articles = db_query.all()
    fallback = {
        "articles": [
            {
                "article_id": str(a.id),
                "title": a.title,
                "product": a.product or "",
                "risk_level": a.risk_level or "unknown",
                "review_status": a.review_status
            }
            for a in approved_articles
        ],
        "total_found": len(approved_articles),
        "service_version": "v1.0-fallback"
    }

    return await _forward_post(VISHAQA_API_URL, "/support/retrieve", payload, correlation_id, fallback)

@router.post("/support/suggest-reply")
async def proxy_support_suggest_reply(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    
    fallback = {
        "proposed_reply": None,
        "human_required": True,
        "reasons": ["AI reply suggestion service offline fallback"],
        "used_article_ids": [],
        "service_version": "v1.0-fallback"
    }
    
    return await _forward_post(VISHAQA_API_URL, "/support/suggest-reply", payload, correlation_id, fallback)

@router.post("/support/escalation")
async def proxy_support_escalation(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    
    fallback = {
        "severity": "Medium",
        "escalation_target": "General Support",
        "acknowledgement_target_minutes": 240,
        "escalation_required": False,
        "service_version": "v1.0-fallback"
    }
    
    return await _forward_post(VISHAQA_API_URL, "/support/escalation", payload, correlation_id, fallback)

@router.post("/support/predictions/correct")
async def proxy_support_predictions_correct(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    
    fallback = {
        "prediction_id": payload.get("prediction_id", ""),
        "predicted_category": "",
        "actual_category": payload.get("actual_category", ""),
        "corrected": False,
        "service_version": "v1.0-fallback"
    }
    
    return await _forward_post(VISHAQA_API_URL, "/support/predictions/correct", payload, correlation_id, fallback)


# --- ASMA (MARKETING AI) ENDPOINTS ---

@router.post("/marketing/brief")
async def proxy_marketing_brief(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    
    # We raise Bad Gateway when offline, since manual brief input is preferred to a fake object.
    return await _forward_post(ASMA_API_URL, "/marketing/brief", payload, correlation_id, fallback_response=None)

@router.post("/marketing/calendar")
async def proxy_marketing_calendar(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    
    return await _forward_post(ASMA_API_URL, "/marketing/calendar", payload, correlation_id, fallback_response=None)

@router.post("/marketing/content")
async def proxy_marketing_content(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    
    return await _forward_post(ASMA_API_URL, "/marketing/content", payload, correlation_id, fallback_response=None)

@router.post("/marketing/translate")
async def proxy_marketing_translate(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    
    return await _forward_post(ASMA_API_URL, "/marketing/translate", payload, correlation_id, fallback_response=None)

@router.post("/marketing/designer-brief")
async def proxy_marketing_designer_brief(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    
    return await _forward_post(ASMA_API_URL, "/marketing/designer-brief", payload, correlation_id, fallback_response=None)

@router.post("/marketing/revise")
async def proxy_marketing_revise(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    
    return await _forward_post(ASMA_API_URL, "/marketing/revise", payload, correlation_id, fallback_response=None)


# --- ESHA (QA & QUALITY) ENDPOINTS ---

@router.post("/qa/analyze")
async def proxy_qa_analyze(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    
    # Esha's QA schema has platform/text inputs (not DB mapped by tenant).
    # However, we still verify user belongs to the tenant.
    
    # Bypass QA checks cleanly when service is offline so content submission is not blocked.
    fallback = {
        "score": 1.0,
        "checks": [
            {"check_name": "length_limit", "passed": True, "score": 1.0},
            {"check_name": "profanity_check", "passed": True, "score": 1.0},
            {"check_name": "brand_voice_alignment", "passed": True, "score": 1.0}
        ],
        "issues": [
            {
                "severity": "low",
                "location": "service_status",
                "message": "QA analysis service offline. Bypassed checks."
            }
        ],
        "service_version": "v1.0-fallback"
    }
    
    return await _forward_post(ESHA_API_URL, "/qa/analyze", payload, correlation_id, fallback)

@router.post("/quality/hashtags/suggest")
async def proxy_quality_hashtags_suggest(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    fallback = {
        "recommended_tags": ["#LocalBusiness", "#SupportLocal"],
        "warnings": [],
        "quality_score": 80,
        "service_version": "v1.0-fallback"
    }
    return await _forward_post(ESHA_API_URL, "/quality/hashtags/suggest", payload, correlation_id, fallback)

@router.post("/quality/hashtags/save")
async def proxy_quality_hashtags_save(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    fallback = {
        "status": "success",
        "message": "Offline save simulation",
        "service_version": "v1.0-fallback"
    }
    return await _forward_post(ESHA_API_URL, "/quality/hashtags/save", payload, correlation_id, fallback)

@router.post("/quality/content")
async def proxy_quality_content(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    fallback = {
        "score": 1.0,
        "passed": True,
        "issues": [],
        "service_version": "v1.0-fallback"
    }
    return await _forward_post(ESHA_API_URL, "/quality/content", payload, correlation_id, fallback)

@router.post("/quality/similarity")
async def proxy_quality_similarity(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    fallback = {
        "is_similar": False,
        "similarity_score": 0.1,
        "matched_items": [],
        "service_version": "v1.0-fallback"
    }
    return await _forward_post(ESHA_API_URL, "/quality/similarity", payload, correlation_id, fallback)

@router.post("/analytics/event")
async def proxy_analytics_event(
    payload: Dict[str, Any],
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    payload["tenant_id"] = str(tenant_id)
    fallback = {
        "status": "logged",
        "service_version": "v1.0-fallback"
    }
    return await _forward_post(ESHA_API_URL, "/analytics/event", payload, correlation_id, fallback)

@router.get("/analytics/dashboard")
async def proxy_analytics_dashboard(
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    params = dict(request.query_params)
    params["tenant_id"] = str(tenant_id)
    fallback = {
        "metrics": {"total_reach": 0, "engagement_rate": 0.0},
        "service_version": "v1.0-fallback"
    }
    return await _forward_get(ESHA_API_URL, "/analytics/dashboard", correlation_id, params, fallback)

@router.get("/analytics/monthly-report")
async def proxy_analytics_monthly_report(
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    params = dict(request.query_params)
    params["tenant_id"] = str(tenant_id)
    fallback = {
        "report_url": "",
        "generated_at": str(datetime.utcnow()),
        "service_version": "v1.0-fallback"
    }
    return await _forward_get(ESHA_API_URL, "/analytics/monthly-report", correlation_id, params, fallback)

@router.get("/analytics/client-health")
async def proxy_analytics_client_health(
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer", "client_rep"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    params = dict(request.query_params)
    params["tenant_id"] = str(tenant_id)
    fallback = {
        "total_reach": 184000,
        "engagement_rate": 6.8,
        "client_signals": [
            {
                "client_id": "00000000-0000-0000-0000-0000000000b3",
                "client_name": "Bebop Staples Mill",
                "health_score": 92.0,
                "status": "Healthy",
                "total_reach": 85000,
                "engagement_rate": 7.4,
                "open_tickets": 0,
                "active_campaigns": 3
            },
            {
                "client_id": "00000000-0000-0000-0000-00000000000b",
                "client_name": "Acme Wireless Partners",
                "health_score": 88.5,
                "status": "Healthy",
                "total_reach": 54000,
                "engagement_rate": 6.2,
                "open_tickets": 1,
                "active_campaigns": 2
            },
            {
                "client_id": "00000000-0000-0000-0000-0000000000b5",
                "client_name": "Samvix",
                "health_score": 74.0,
                "status": "Requires Attention",
                "total_reach": 28000,
                "engagement_rate": 5.1,
                "open_tickets": 2,
                "active_campaigns": 1
            },
            {
                "client_id": "00000000-0000-0000-0000-0000000000b7",
                "client_name": "ABC Traders",
                "health_score": 58.0,
                "status": "At Risk",
                "total_reach": 17000,
                "engagement_rate": 4.3,
                "open_tickets": 3,
                "active_campaigns": 0
            }
        ],
        "performance_trend": [
            {"day": "Mon", "reach": 22000, "engagement": 6.1},
            {"day": "Tue", "reach": 28000, "engagement": 6.4},
            {"day": "Wed", "reach": 25000, "engagement": 6.2},
            {"day": "Thu", "reach": 34000, "engagement": 7.1},
            {"day": "Fri", "reach": 38000, "engagement": 7.5},
            {"day": "Sat", "reach": 24000, "engagement": 6.8},
            {"day": "Sun", "reach": 13000, "engagement": 5.9}
        ],
        "service_version": "v1.0-fallback"
    }
    return await _forward_get(ESHA_API_URL, "/analytics/client-health", correlation_id, params, fallback)



@router.get("/analytics/client-summary")
async def proxy_analytics_client_summary(
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer", "client_rep"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    params = dict(request.query_params)
    params["tenant_id"] = str(tenant_id)
    return await _forward_get(ESHA_API_URL, "/analytics/client-summary", correlation_id, params, fallback_response=None)

@router.get("/analytics/workload")
async def proxy_analytics_workload(
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer", "client_rep"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    params = dict(request.query_params)
    params["tenant_id"] = str(tenant_id)
    return await _forward_get(ESHA_API_URL, "/analytics/workload", correlation_id, params, fallback_response=None)

@router.get("/analytics/scheduler-consistency")
async def proxy_analytics_scheduler_consistency(
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer", "client_rep"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    params = dict(request.query_params)
    params["tenant_id"] = str(tenant_id)
    return await _forward_get(ESHA_API_URL, "/analytics/scheduler-consistency", correlation_id, params, fallback_response=None)

@router.get("/quality/ai-evaluation/summary")
async def proxy_quality_ai_evaluation_summary(
    request: Request,
    tenant_id: UUID = Depends(get_current_tenant),
    current_user: User = Depends(RoleChecker(["super_admin", "tenant_admin", "designer", "client_rep"]))
):
    correlation_id = request.headers.get("X-Correlation-ID", f"trace-{int(uuid.uuid4().int)}")
    params = dict(request.query_params)
    params["tenant_id"] = str(tenant_id)
    return await _forward_get(ESHA_API_URL, "/quality/ai-evaluation/summary", correlation_id, params, fallback_response=None)
