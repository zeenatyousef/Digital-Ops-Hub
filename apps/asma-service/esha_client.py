"""
apps/asma-service/esha_client.py

Thin wrapper around Esha's hashtag-signature/quality service
(POST /quality/hashtags/suggest on esha-service).

STATUS (as of this writing): Esha's service only runs on her own local
machine (localhost:8000) — it isn't reachable through the shared gateway
proxy yet, so calls from this service will fail with a connection error
until Zeenat wires up the proxy route. That's expected, not a bug — this
client is written to degrade gracefully rather than crash /marketing/content
when the hashtag service can't be reached.

Once the gateway route exists, set ESHA_API_URL in .env to the routed
address (see .env.example — it currently points at http://localhost:8003,
matching the esha-service scaffold convention) and this will start working
without any code changes here.
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

ESHA_API_URL = os.getenv("ESHA_API_URL", "http://localhost:8003")


def get_hashtag_suggestions(
    client: str,
    platform: str,
    existing_tags: list[str] | None = None,
) -> dict | None:
    """
    Calls Esha's POST /quality/hashtags/suggest.

    Returns a dict shaped like:
        {
            "recommended_tags": [...],
            "warnings": [{"type": ..., "tag": ..., "message": ...}, ...],
            "quality_score": int,
        }

    Returns None (does NOT raise) if the service is unreachable or errors —
    hashtag suggestions are a nice-to-have for content generation, not a
    hard requirement, so a failure here should never block a caption from
    being generated. Callers should treat None as "no suggestions available
    right now" and leave hashtags_ref empty rather than fail the request.

    NOTE: if a client+platform combo has no saved hashtag set yet, Esha's
    service itself falls back to generic tags (#LocalBusiness,
    #SupportLocal) rather than erroring — that's handled on her end, not here.
    """
    payload = {
        "tags": existing_tags or [],
        "client": client,
        "platform": platform,
    }

    try:
        with httpx.Client(timeout=1.0) as http_client:
            response = http_client.post(
                f"{ESHA_API_URL}/quality/hashtags/suggest",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
    except httpx.RequestError:
        # Service unreachable (not gateway-wired yet, or down) — expected
        # for now, degrade gracefully.
        return None
    except httpx.HTTPStatusError:
        # Service reachable but returned an error — also degrade gracefully
        # rather than failing the whole content-generation request.
        return None