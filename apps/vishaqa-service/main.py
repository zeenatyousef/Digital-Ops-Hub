from fastapi import FastAPI, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
import re
import json
import uuid

from packages.database.session import get_db
from packages.database.models import AIRun, TicketPrediction, ConversationSummary, KBArticle, TicketTaxonomy
app = FastAPI(title="Vishaqa - AI Support Intelligence Service")

# ---- Request/Response Models ----
class TicketInput(BaseModel):
    tenant_id: str
    message: str
    client_id: Optional[str] = None

class ClassificationResult(BaseModel):
    product: str
    category: str
    severity: str
    owner_team: str
    confidence: float
    human_required: bool
    priority: Optional[int] = None
    service_version: str = "v1.0"


# ---- Helper: word-boundary aware matching ----
def has_word(text: str, word: str) -> bool:
    """Check if a whole word (not a substring inside another word) exists in the text."""
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def has_phrase(text: str, phrase: str) -> bool:
    """Check if an exact phrase (words in that order, next to each other) exists in the text."""
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def matches_any_combo(text: str, word_combos: list) -> bool:
    """
    Check if ANY of the given word-combinations are fully present in the text.
    Each combo is a list of words that must ALL appear (in any order, anywhere in the text).
    Example: combo ["production", "down"] matches "production system is completely down".
    """
    return any(all(has_word(text, w) for w in combo) for combo in word_combos)


# ---- Full taxonomy-based rule classifier ----
def classify_message(message: str, db: Optional[Session] = None, tenant_id: Optional[uuid.UUID] = None) -> ClassificationResult:
    text = message.lower()

    # ---- DYNAMIC DB-DRIVEN TAXONOMY CLASSIFICATION ----
    if db is not None and tenant_id is not None:
        try:
            db_rules = db.query(TicketTaxonomy).filter(
                TicketTaxonomy.tenant_id == tenant_id
            ).order_by(TicketTaxonomy.priority.asc()).all()

            if db_rules:
                for rule in db_rules:
                    rules_def = rule.rules_definition
                    while isinstance(rules_def, str):
                        rules_def = json.loads(rules_def)

                    if not rules_def:
                        continue

                    combos = rules_def.get("combos", [])
                    phrases = rules_def.get("phrases", [])
                    exclusions = rules_def.get("exclusions", [])

                    if exclusions and any(has_word(text, ex) for ex in exclusions):
                        continue

                    matches = False
                    if combos and matches_any_combo(text, combos):
                        matches = True
                    elif phrases and any(has_phrase(text, p) for p in phrases):
                        matches = True

                    if matches:
                        return ClassificationResult(
                            product=rule.product,
                            category=rule.category,
                            severity=rule.severity,
                            owner_team=rule.owner_team,
                            confidence=rule.confidence_threshold or 0.9,
                            human_required=rule.human_required,
                            priority=rule.priority
                        )
                # If tenant has rules defined in DB, but none of them matched, return default fallback
                return ClassificationResult(
                    product="Unclassified", category="Needs manual review",
                    severity="Medium", owner_team="General Support",
                    confidence=0.4, human_required=True, priority=100
                )
        except Exception:
            # Fall back to static rules on any DB error
            pass


    # ---- GUARDRAILS FIRST — always human_required=True ----
    # Guardrails are recall-biased on purpose: missing a real security/financial/
    # destructive/outage case is worse than an extra manual review, so each
    # category includes broader synonym coverage rather than a single exact phrase.
    #
    # CONFIDENCE CALIBRATION NOTE: values below are calibrated against the real
    # 105-case benchmark (NW_Vishaqa_Benchmark_Dataset.xlsx / Vishaqa_Evaluation_
    # Report.xlsx), using Laplace/add-1 smoothing so small sample sizes don't
    # produce overconfident 1.0 scores. Fallback confidence (0.4) is intentionally
    # kept low regardless of benchmark pass rate — that category signals "the
    # model is unsure", so its confidence should not rise just because the
    # fallback path itself was triggered correctly in tests.

    security_incident_combos = [
        ["hacked"],
        ["hack"],
        ["breach"],
        ["breached"],
        ["security", "incident"],
        ["unauthorized", "access"],
        ["compromised"],
    ]

    security_combos = [
        ["password"],
        ["credential"],
        ["credentials"],
        ["login", "access"],
        ["reset", "my"],
        ["account", "locked"],
        ["locked", "out"],
        ["logged", "in"],
        ["logged", "into"],
    ]

    destructive_combos = [
        ["delete", "data"],
        ["delete", "my", "data"],
        ["wipe", "database"],
        ["delete", "database"],
        ["remove", "all", "data"],
        ["erase", "data"],
        ["drop", "table"],
        ["remove", "all", "records"],
        ["delete", "records"],
        ["erase", "records"],
    ]

    financial_combos = [
        ["refund"],
        ["billing", "dispute"],
        ["payment", "promise"],
        ["charge", "me"],
        ["charged", "me"],
        ["money", "back"],
        ["reimburse"],
        ["reimbursement"],
        ["overcharged"],
        ["wrong", "amount"],
        ["billed"],
    ]

    outage_combos = [
        ["production", "down"],
        ["system", "down"],
        ["everything", "down"],
        ["site", "down"],
        ["service", "down"],
        ["completely", "down"],
        ["outage"],
        ["completely", "blocked"],
        ["invoice", "blocked"],
        ["entire", "down"],
    ]

    # ---- Check guardrail categories in priority order ----
    if matches_any_combo(text, security_incident_combos):
        return ClassificationResult(
            product="Security", category="Suspected security incident/breach",
            severity="Critical", owner_team="Security/Admin",
            confidence=0.91, human_required=True, priority=10
        )
 
    if matches_any_combo(text, security_combos):
        return ClassificationResult(
            product="Security", category="Password reset/login access issue",
            severity="High", owner_team="Security/Admin",
            confidence=0.90, human_required=True, priority=20
        )
 
    if matches_any_combo(text, destructive_combos):
        return ClassificationResult(
            product="Destructive Action", category="Request to delete/wipe data",
            severity="Critical", owner_team="Admin/DB Owner",
            confidence=0.89, human_required=True, priority=30
        )
 
    if matches_any_combo(text, financial_combos):
        return ClassificationResult(
            product="Financial", category="Refund/billing dispute",
            severity="High", owner_team="Account Manager",
            confidence=0.93, human_required=True, priority=40
        )
 
    if matches_any_combo(text, outage_combos) or has_phrase(text, "not working at all"):
        return ClassificationResult(
            product="Production Outage", category="Critical production system down",
            severity="Critical", owner_team="Director/Escalation",
            confidence=0.93, human_required=True, priority=50
        )
 
    # ---- FBR Digital Invoicing ----
    if has_word(text, "fbr") or "ora-" in text or has_word(text, "invoice") or has_word(text, "invoices"):
        if has_word(text, "slow"):
            return ClassificationResult(
                product="FBR Digital Invoicing", category="Slow invoice processing",
                severity="Medium", owner_team="Oracle Support",
                confidence=0.82, human_required=False, priority=60
            )
        if has_word(text, "mismatch") or has_word(text, "validation"):
            return ClassificationResult(
                product="FBR Digital Invoicing", category="Invoice data mismatch/validation error",
                severity="High", owner_team="Oracle/FBR Integration Support",
                confidence=0.87, human_required=False, priority=70
            )
        return ClassificationResult(
            product="FBR Digital Invoicing", category="Invoice won't post/gateway error",
            severity="Critical", owner_team="Oracle/FBR Integration Support",
            confidence=0.92, human_required=False, priority=80
        )

    # ---- POS ----
    if has_word(text, "pos") or has_word(text, "scanner") or has_word(text, "barcode") or ((has_word(text, "receipt") or has_word(text, "receipts")) and (has_word(text, "printer") or has_word(text, "print") or has_word(text, "printing"))):
        if has_word(text, "scan") or has_word(text, "scanning") or has_word(text, "print") or has_word(text, "printing"):
            return ClassificationResult(
                product="POS", category="POS not scanning/printing",
                severity="High", owner_team="POS Product Support",
                confidence=0.82, human_required=False, priority=90
            )
        if has_word(text, "offline"):
            return ClassificationResult(
                product="POS", category="POS device offline",
                severity="Medium", owner_team="POS Product Support",
                confidence=0.78, human_required=False, priority=100
            )
        return ClassificationResult(
            product="POS", category="New user setup/how-to question",
            severity="Low", owner_team="POS Product Support",
            confidence=0.72, human_required=False, priority=110
        )
 
    # ---- Website ----
    if has_word(text, "checkout") or "payment error" in text or has_word(text, "website") or has_word(text, "homepage"):
        if has_word(text, "down"):
            return ClassificationResult(
                product="Website", category="Site completely down",
                severity="Critical", owner_team="Web Lead",
                confidence=0.80, human_required=False, priority=56
            )
        if has_word(text, "checkout") or has_word(text, "payment"):
            return ClassificationResult(
                product="Website", category="Checkout/payment error",
                severity="High", owner_team="Web Lead",
                confidence=0.78, human_required=False, priority=130
            )
        return ClassificationResult(
            product="Website", category="Minor design/UI bug",
            severity="Low", owner_team="Web Lead",
            confidence=0.60, human_required=False, priority=140
        )
 
    # ---- Hosting ----
    if has_word(text, "hosting") or has_word(text, "server"):
        if has_word(text, "down"):
            return ClassificationResult(
                product="Hosting", category="Server down",
                severity="Critical", owner_team="Web Lead",
                confidence=0.85, human_required=False, priority=55
            )
        return ClassificationResult(
            product="Hosting", category="Slow server response",
            severity="Medium", owner_team="Web Lead",
            confidence=0.75, human_required=False, priority=160
        )
 
    # ---- Marketing/Social ----
    if has_word(text, "poster") or has_word(text, "social") or has_word(text, "post"):
        return ClassificationResult(
            product="Marketing/Social", category="Correction/scheduling issue",
            severity="Medium", owner_team="Marketing Lead",
            confidence=0.75, human_required=False, priority=170
        )
 
    # ---- Fallback: unclassified, needs human review ----
    return ClassificationResult(
        product="Unclassified", category="Needs manual review",
        severity="Medium", owner_team="General Support",
        confidence=0.4, human_required=True, priority=100
    )

# ---- Endpoints ----
@app.post("/support/classify", response_model=ClassificationResult)
def classify_ticket(ticket: TicketInput, db: Session = Depends(get_db)):
    try:
        tenant_uuid = uuid.UUID(ticket.tenant_id)
    except ValueError:
        tenant_uuid = None

    result = classify_message(ticket.message, db=db, tenant_id=tenant_uuid)

    if tenant_uuid is None:
        # invalid tenant_id — skip DB logging, still return the classification result
        return result

    # Log this AI run for evaluation/monitoring
    try:
        ai_run = AIRun(
            tenant_id=tenant_uuid,
            run_type="classify",
            status="success",
            input_data=json.dumps({"message": ticket.message}),
            output_data=result.model_dump_json()
        )
        db.add(ai_run)

        # Save the prediction so it can later be corrected/evaluated
        prediction = TicketPrediction(
            tenant_id=tenant_uuid,
            predicted_category=result.category,
            confidence=result.confidence
        )
        db.add(prediction)

        db.commit()
    except Exception:
        # A well-formed but non-existent tenant_id causes an FK violation on
        # commit. Logging/prediction-save failures must never break the
        # actual classification response — roll back and still return it.
        db.rollback()

    return result

@app.get("/support/health")
def health_check():
    return {"status": "ok", "service": "vishaqa-support-ai", "timestamp": str(datetime.now())}

# ---- Summarize Endpoint ----
class ConversationMessage(BaseModel):
    message_id: str
    sender: str  # "client" or "agent"
    text: str
    timestamp: Optional[str] = None

class SummarizeInput(BaseModel):
    tenant_id: str
    client_room_id: str
    messages: list[ConversationMessage]

class SummarizeResult(BaseModel):
    summary_text: str
    source_message_ids: list[str]
    extracted_actions: list[str]
    extracted_dates: list[str]
    missing_information: list[str]
    sentiment: str
    service_version: str = "v1.0"


def summarize_conversation(data: SummarizeInput) -> SummarizeResult:
    all_text = " ".join([m.text for m in data.messages])
    text_lower = all_text.lower()
    message_ids = [m.message_id for m in data.messages]

    negative_words = ["angry", "frustrated", "not working", "still broken", "unacceptable", "urgent"]
    positive_words = ["thank you", "thanks", "appreciate", "great", "resolved"]

    if any(word in text_lower for word in negative_words):
        sentiment = "negative"
    elif any(word in text_lower for word in positive_words):
        sentiment = "positive"
    else:
        sentiment = "neutral"

    extracted_actions = []
    action_triggers = ["please", "need", "can you", "requesting", "want to"]
    for m in data.messages:
        if any(trigger in m.text.lower() for trigger in action_triggers):
            extracted_actions.append(m.text)

    date_pattern = r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*)\b"
    extracted_dates = re.findall(date_pattern, all_text, re.IGNORECASE)
    extracted_dates = [d[0] if isinstance(d, tuple) else d for d in extracted_dates]

    missing_information = []

    reference_pattern = r"(ticket|order|invoice|reference)[\s#:]*\d+"
    has_reference_number = re.search(reference_pattern, text_lower)
    if not has_reference_number:
        missing_information.append("Reference/order/ticket number not provided (only mentioned in words, no actual number)")

    if not extracted_dates:
        missing_information.append("No specific date mentioned")

    client_messages = [m.text for m in data.messages if m.sender == "client"]
    summary_text = " ".join(client_messages[:3])
    if len(summary_text) > 300:
        summary_text = summary_text[:300] + "..."

    return SummarizeResult(
        summary_text=summary_text,
        source_message_ids=message_ids,
        extracted_actions=extracted_actions,
        extracted_dates=extracted_dates,
        missing_information=missing_information,
        sentiment=sentiment
    )


@app.post("/support/summarize", response_model=SummarizeResult)
def summarize_ticket(data: SummarizeInput, db: Session = Depends(get_db)):
    result = summarize_conversation(data)

    try:
        tenant_uuid = uuid.UUID(data.tenant_id)
        client_room_uuid = uuid.UUID(data.client_room_id)
    except ValueError:
        # invalid tenant_id/client_room_id — skip DB logging, still return the result
        return result

    try:
        ai_run = AIRun(
            tenant_id=tenant_uuid,
            run_type="summarize",
            status="success",
            input_data=json.dumps({"client_room_id": data.client_room_id, "message_count": len(data.messages)}),
            output_data=result.model_dump_json()
        )
        db.add(ai_run)

        summary_record = ConversationSummary(
            tenant_id=tenant_uuid,
            client_room_id=client_room_uuid,
            summary_text=result.summary_text
        )
        db.add(summary_record)

        db.commit()
    except Exception:
        # Well-formed but non-existent tenant_id/client_room_id -> FK
        # violation. Logging must never break the actual summarize response.
        db.rollback()

    return result
# ---- Knowledge Base Retrieval Endpoint ----
class RetrieveInput(BaseModel):
    tenant_id: str
    product: str
    query: Optional[str] = None


class KBArticleResult(BaseModel):
    article_id: str
    title: str
    product: str
    risk_level: str
    review_status: str


class RetrieveResult(BaseModel):
    articles: list[KBArticleResult]
    total_found: int
    service_version: str = "v1.0"


def retrieve_articles(data: RetrieveInput, db: Session) -> RetrieveResult:
    try:
        tenant_uuid = uuid.UUID(data.tenant_id)
    except ValueError:
        return RetrieveResult(articles=[], total_found=0)

    query = db.query(KBArticle).filter(
        KBArticle.tenant_id == tenant_uuid,
        KBArticle.review_status == "approved",
    )

    if data.product:
        query = query.filter(KBArticle.product.ilike(data.product))

    articles = query.all()

    matched = [
        KBArticleResult(
            article_id=str(article.id),
            title=article.title,
            product=article.product or "",
            risk_level=article.risk_level or "unknown",
            review_status=article.review_status,
        )
        for article in articles
    ]

    return RetrieveResult(articles=matched, total_found=len(matched))


@app.post("/support/retrieve", response_model=RetrieveResult)
def retrieve_knowledge(data: RetrieveInput, db: Session = Depends(get_db)):
    return retrieve_articles(data, db)
# ---- Suggest Reply Endpoint ----

class SuggestReplyInput(BaseModel):
    tenant_id: str
    ticket_message: str
    product: str
    retrieved_article_ids: Optional[list[str]] = []


class SuggestReplyResult(BaseModel):
    proposed_reply: Optional[str]
    human_required: bool
    reasons: list[str]
    used_article_ids: list[str]
    service_version: str = "v1.0"


def suggest_reply(data: SuggestReplyInput, db: Optional[Session] = None, tenant_id: Optional[uuid.UUID] = None) -> SuggestReplyResult:
    classification = classify_message(data.ticket_message, db=db, tenant_id=tenant_id)

    if classification.human_required:
        return SuggestReplyResult(
            proposed_reply=None,
            human_required=True,
            reasons=[
                f"Ticket classified as '{classification.category}' under product '{classification.product}', "
                f"which requires human review per policy."
            ],
            used_article_ids=[]
        )

    if not data.retrieved_article_ids:
        return SuggestReplyResult(
            proposed_reply=None,
            human_required=True,
            reasons=["No approved knowledge article available to base a safe reply on."],
            used_article_ids=[]
        )

    proposed = (
        f"Thank you for reaching out. Based on our approved documentation "
        f"(reference: {', '.join(data.retrieved_article_ids)}), our team has identified this as a "
        f"'{classification.category}' issue related to {classification.product}. "
        f"We are reviewing this and will follow up with next steps shortly."
    )

    return SuggestReplyResult(
        proposed_reply=proposed,
        human_required=False,
        reasons=["Reply generated from approved knowledge article(s) within guardrail policy."],
        used_article_ids=data.retrieved_article_ids
    )


@app.post("/support/suggest-reply", response_model=SuggestReplyResult)
def suggest_reply_endpoint(data: SuggestReplyInput, db: Session = Depends(get_db)):
    try:
        tenant_uuid = uuid.UUID(data.tenant_id)
    except ValueError:
        tenant_uuid = None

    result = suggest_reply(data, db=db, tenant_id=tenant_uuid)

    try:
        tenant_uuid = uuid.UUID(data.tenant_id)
        ai_run = AIRun(
            tenant_id=tenant_uuid,
            run_type="suggest-reply",
            status="success",
            input_data=json.dumps({"ticket_message": data.ticket_message, "product": data.product}),
            output_data=result.model_dump_json()
        )
        db.add(ai_run)
        db.commit()
    except Exception:
        # Covers invalid tenant_id string AND well-formed but non-existent
        # tenant_id (FK violation on commit).
        db.rollback()

    return result

# ---- Escalation Endpoint ----

class EscalationInput(BaseModel):
    tenant_id: str
    ticket_message: str
    severity: Optional[str] = None  # if not provided, will auto-classify


class EscalationResult(BaseModel):
    severity: str
    escalation_target: str
    acknowledgement_target_minutes: int
    escalation_required: bool
    service_version: str = "v1.0"


def determine_escalation(data: EscalationInput, db: Optional[Session] = None, tenant_id: Optional[uuid.UUID] = None) -> EscalationResult:
    if data.severity:
        severity = data.severity
        owner_team = None
    else:
        classification = classify_message(data.ticket_message, db=db, tenant_id=tenant_id)
        severity = classification.severity
        owner_team = classification.owner_team

    if severity == "Critical":
        return EscalationResult(
            severity=severity,
            escalation_target=owner_team or "Director/Escalation",
            acknowledgement_target_minutes=15,
            escalation_required=True
        )
    elif severity == "High":
        return EscalationResult(
            severity=severity,
            escalation_target=owner_team or "Team Lead",
            acknowledgement_target_minutes=60,
            escalation_required=True
        )
    elif severity == "Medium":
        return EscalationResult(
            severity=severity,
            escalation_target=owner_team or "General Support",
            acknowledgement_target_minutes=240,
            escalation_required=False
        )
    else:  # Low
        return EscalationResult(
            severity=severity,
            escalation_target=owner_team or "General Support",
            acknowledgement_target_minutes=1440,
            escalation_required=False
        )


@app.post("/support/escalation", response_model=EscalationResult)
def escalation_endpoint(data: EscalationInput, db: Session = Depends(get_db)):
    try:
        tenant_uuid = uuid.UUID(data.tenant_id)
    except ValueError:
        tenant_uuid = None

    result = determine_escalation(data, db=db, tenant_id=tenant_uuid)

    try:
        tenant_uuid = uuid.UUID(data.tenant_id)
        ai_run = AIRun(
            tenant_id=tenant_uuid,
            run_type="escalation",
            status="success",
            input_data=json.dumps({"ticket_message": data.ticket_message, "severity": data.severity}),
            output_data=result.model_dump_json()
        )
        db.add(ai_run)
        db.commit()
    except Exception:
        # Covers invalid tenant_id string AND well-formed but non-existent
        # tenant_id (FK violation on commit).
        db.rollback()

    return result

# ---- Correction Feedback Endpoint ----
class CorrectionInput(BaseModel):
    tenant_id: str
    prediction_id: str
    actual_category: str
    corrected_by_id: Optional[str] = None


class CorrectionResult(BaseModel):
    prediction_id: str
    predicted_category: str
    actual_category: str
    corrected: bool
    service_version: str = "v1.0"


@app.post("/support/predictions/correct", response_model=CorrectionResult)
def correct_prediction(data: CorrectionInput, db: Session = Depends(get_db)):
    try:
        tenant_uuid = uuid.UUID(data.tenant_id)
        prediction_uuid = uuid.UUID(data.prediction_id)
    except ValueError:
        return CorrectionResult(
            prediction_id=data.prediction_id,
            predicted_category="",
            actual_category=data.actual_category,
            corrected=False
        )

    prediction = db.query(TicketPrediction).filter(
        TicketPrediction.id == prediction_uuid,
        TicketPrediction.tenant_id == tenant_uuid,
    ).first()

    if not prediction:
        return CorrectionResult(
            prediction_id=data.prediction_id,
            predicted_category="",
            actual_category=data.actual_category,
            corrected=False
        )

    predicted_category = prediction.predicted_category
    prediction.actual_category = data.actual_category

    if data.corrected_by_id:
        try:
            prediction.corrected_by_id = uuid.UUID(data.corrected_by_id)
        except ValueError:
            pass

    db.commit()

    return CorrectionResult(
        prediction_id=data.prediction_id,
        predicted_category=predicted_category,
        actual_category=data.actual_category,
        corrected=True
    )