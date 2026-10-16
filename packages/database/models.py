import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, Integer, Table, Enum, Float, JSON, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from .session import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    status = Column(String(50), default="active")  # active, suspended
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    clients = relationship("Client", back_populates="tenant", cascade="all, delete-orphan")
    campaigns = relationship("Campaign", back_populates="tenant", cascade="all, delete-orphan")
    audit_events = relationship("AuditEvent", back_populates="tenant", cascade="all, delete-orphan")

    # Esha Module
    hashtag_sets = relationship("HashtagSet", back_populates="tenant", cascade="all, delete-orphan")
    quality_runs = relationship("QualityRun", back_populates="tenant", cascade="all, delete-orphan")
    analytics_events = relationship("AnalyticsEvent", back_populates="tenant", cascade="all, delete-orphan")
    report_snapshots = relationship("ReportSnapshot", back_populates="tenant", cascade="all, delete-orphan")
    test_cases = relationship("TestCase", back_populates="tenant", cascade="all, delete-orphan")
    defects = relationship("Defect", back_populates="tenant", cascade="all, delete-orphan")

    # Asma Module
    brand_profiles = relationship("BrandProfile", back_populates="tenant", cascade="all, delete-orphan")
    campaign_briefs = relationship("CampaignBrief", back_populates="tenant", cascade="all, delete-orphan")
    calendar_items = relationship("CalendarItem", back_populates="tenant", cascade="all, delete-orphan")
    designer_briefs = relationship("DesignerBrief", back_populates="tenant", cascade="all, delete-orphan")

    # Vishaqa Module
    ticket_taxonomies = relationship("TicketTaxonomy", back_populates="tenant", cascade="all, delete-orphan")
    kb_articles = relationship("KBArticle", back_populates="tenant", cascade="all, delete-orphan")
    ai_runs = relationship("AIRun", back_populates="tenant", cascade="all, delete-orphan")
    ticket_predictions = relationship("TicketPrediction", back_populates="tenant", cascade="all, delete-orphan")
    conversation_summaries = relationship("ConversationSummary", back_populates="tenant", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)  # super_admin, tenant_admin, designer, client_rep
    is_active = Column(Boolean, default=True)
    phone_number = Column(String(50), nullable=True)  # Masked in DTOs
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    sent_messages = relationship("Message", back_populates="sender")
    audit_events = relationship("AuditEvent", back_populates="user")

    # Vishaqa Module
    corrected_predictions = relationship("TicketPrediction", back_populates="corrected_by")
    reviewed_summaries = relationship("ConversationSummary", back_populates="reviewer")

    # Asma Module / Content Versions
    reviewed_versions = relationship("ContentVersion", foreign_keys="[ContentVersion.reviewer_id]", back_populates="reviewer")

    # Esha Module
    reviewed_quality_runs = relationship("QualityRun", foreign_keys="[QualityRun.reviewer_id]", back_populates="reviewer")
    defects = relationship("Defect", foreign_keys="[Defect.owner_id]", back_populates="owner")


class Client(Base):
    __tablename__ = "clients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    company_name = Column(String(255), nullable=False)
    industry = Column(String(255), nullable=True)
    contact_email = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="clients")
    client_rooms = relationship("ClientRoom", back_populates="client", cascade="all, delete-orphan")
    campaigns = relationship("Campaign", back_populates="client", cascade="all, delete-orphan")
    brand_profiles = relationship("BrandProfile", back_populates="client", cascade="all, delete-orphan")
    hashtag_sets = relationship("HashtagSet", back_populates="client")
    analytics_events = relationship("AnalyticsEvent", back_populates="client")
    report_snapshots = relationship("ReportSnapshot", back_populates="client", cascade="all, delete-orphan")


class ClientRoom(Base):
    __tablename__ = "client_rooms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), default="active")  # active, closed
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    client = relationship("Client", back_populates="client_rooms")
    messages = relationship("Message", back_populates="client_room", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_room_id = Column(UUID(as_uuid=True), ForeignKey("client_rooms.id", ondelete="CASCADE"), nullable=True)
    conversation_id = Column(UUID(as_uuid=True), nullable=True)  # For personal 1:1/group DM
    sender_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    parent_message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    content_type = Column(String(50), default="text")  # text, file, system
    content = Column(Text, nullable=False)
    visibility = Column(String(50), default="external")  # external (visible to client), internal (designer/admin only)
    read_at = Column(DateTime, nullable=True)
    edited_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    client_room = relationship("ClientRoom", back_populates="messages")
    sender = relationship("User", back_populates="sent_messages")
    parent_message = relationship("Message", remote_side=[id], back_populates="replies")
    replies = relationship("Message", back_populates="parent_message")
    mentions = relationship("MessageMention", back_populates="message", cascade="all, delete-orphan")
    attachments = relationship("MessageAttachment", back_populates="message", cascade="all, delete-orphan")

    @property
    def sender_role(self) -> Optional[str]:
        return self.sender.role if self.sender else None


class MessageMention(Base):
    __tablename__ = "message_mentions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    mentioned_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    message = relationship("Message", back_populates="mentions")
    mentioned_user = relationship("User")


class MessageAttachment(Base):
    __tablename__ = "message_attachments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    file_url = Column(Text, nullable=False)
    file_name = Column(String(255), nullable=True)
    file_type = Column(String(100), nullable=True)
    file_size = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    message = relationship("Message", back_populates="attachments")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    status = Column(String(50), default="draft")  # draft, pending_approval, approved, scheduled, published
    scheduled_publish_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    client = relationship("Client", back_populates="campaigns")
    tenant = relationship("Tenant", back_populates="campaigns")
    versions = relationship("ContentVersion", back_populates="campaign", cascade="all, delete-orphan")
    publishing_jobs = relationship("PublishingJob", back_populates="campaign", cascade="all, delete-orphan")


class ContentVersion(Base):
    __tablename__ = "content_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    version_number = Column(Integer, nullable=False, default=1)
    ai_output = Column(Text, nullable=True)
    edited_content = Column(Text, nullable=True)
    status = Column(String(50), default="pending")  # pending, approved, rejected
    approved_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # New fields requested for Asma Module
    platform = Column(String(100), nullable=True)
    language = Column(String(100), nullable=True)
    caption = Column(Text, nullable=True)
    cta = Column(Text, nullable=True)
    hashtags_reference = Column(Text, nullable=True)
    reviewer_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    campaign = relationship("Campaign", back_populates="versions")
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    reviewer = relationship("User", foreign_keys=[reviewer_id], back_populates="reviewed_versions")
    quality_runs = relationship("QualityRun", back_populates="content_version", cascade="all, delete-orphan")


class PublishingJob(Base):
    __tablename__ = "publishing_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), default="queued")  # queued, processing, completed, failed, manual_handoff
    idempotency_key = Column(String(255), unique=True, nullable=False)
    retry_count = Column(Integer, default=0)
    error_logs = Column(Text, nullable=True)
    scheduled_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    platform_post_id = Column(String(255), nullable=True)
    manual_proof = Column(Text, nullable=True)

    # Relationships
    campaign = relationship("Campaign", back_populates="publishing_jobs")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action_name = Column(String(255), nullable=False)  # message_deleted, campaign_approved, etc.
    entity_name = Column(String(100), nullable=False)  # Message, Campaign, etc.
    entity_id = Column(UUID(as_uuid=True), nullable=True)
    diff_data = Column(Text, nullable=True)  # JSON or text diff
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="audit_events")
    user = relationship("User", back_populates="audit_events")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ==============================================================================
# Esha Module (Quality & Analytics)
# ==============================================================================

class HashtagSet(Base):
    __tablename__ = "hashtag_sets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(255), nullable=False)
    category = Column(String(50), nullable=True)  # brand, local, campaign, industry
    platform = Column(String(50), nullable=True)  # instagram, facebook, twitter, linkedin, tiktok
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="hashtag_sets")
    client = relationship("Client", back_populates="hashtag_sets")
    hashtag_items = relationship("HashtagItem", back_populates="hashtag_set", cascade="all, delete-orphan")


class HashtagItem(Base):
    __tablename__ = "hashtag_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hashtag_set_id = Column(UUID(as_uuid=True), ForeignKey("hashtag_sets.id", ondelete="CASCADE"), nullable=False)
    tag = Column(String(255), nullable=False)
    exclusions = Column(Text, nullable=True)  # JSON array of tags banned in combination
    performance_score = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    hashtag_set = relationship("HashtagSet", back_populates="hashtag_items")


class QualityRun(Base):
    __tablename__ = "quality_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    content_version_id = Column(UUID(as_uuid=True), ForeignKey("content_versions.id", ondelete="SET NULL"), nullable=True)
    input_version = Column(String(255), nullable=True)
    content = Column(Text, nullable=True)
    run_type = Column(String(100), nullable=False)  # hashtags, content, similarity
    checks = Column(Text, nullable=True)  # JSON per-check breakdown
    issues = Column(Text, nullable=True)  # JSON array of {severity, location, message}
    score = Column(Float, nullable=True)
    results = Column(Text, nullable=True)  # JSON or text analysis output
    rule_version = Column(String(50), nullable=True)
    reviewer_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="quality_runs")
    content_version = relationship("ContentVersion", back_populates="quality_runs")
    reviewer = relationship("User", foreign_keys=[reviewer_id], back_populates="reviewed_quality_runs")


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=True)
    event_type = Column(String(100), nullable=False)
    object_type = Column(String(100), nullable=True)  # e.g., campaign, content_version, ticket
    object_id = Column(UUID(as_uuid=True), nullable=True)  # polymorphic reference
    metrics = Column(Text, nullable=True)  # JSON reach, impressions, etc.
    event_data = Column(Text, nullable=True)  # JSON or text metadata
    source = Column(String(100), nullable=True)
    occurred_at = Column(DateTime, nullable=True)
    idempotency_key = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="analytics_events")
    client = relationship("Client", back_populates="analytics_events")


class ReportSnapshot(Base):
    __tablename__ = "report_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    report_type = Column(String(100), nullable=False)  # e.g., dashboard, monthly-report
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    dataset = Column(Text, nullable=False)  # JSON snapshot payload
    completeness = Column(Text, nullable=True)  # JSON completeness metadata
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="report_snapshots")
    client = relationship("Client", back_populates="report_snapshots")


class TestCase(Base):
    __tablename__ = "test_cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    scenario = Column(Text, nullable=False)
    expected_result = Column(Text, nullable=False)
    test_group = Column(String(100), nullable=False)  # e.g. hashtags, content_quality, analytics, ai_evaluation, regression, smoke
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="test_cases")
    test_runs = relationship("TestRun", back_populates="test_case", cascade="all, delete-orphan")


class TestRun(Base):
    __tablename__ = "test_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_case_id = Column(UUID(as_uuid=True), ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False)
    actual_result = Column(Text, nullable=False)
    status = Column(String(50), nullable=False)  # pass, fail, blocked
    evidence_url = Column(String(500), nullable=True)
    run_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    test_case = relationship("TestCase", back_populates="test_runs")
    defects = relationship("Defect", back_populates="test_run", cascade="all, delete-orphan")


class Defect(Base):
    __tablename__ = "defects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    test_run_id = Column(UUID(as_uuid=True), ForeignKey("test_runs.id", ondelete="SET NULL"), nullable=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    severity = Column(String(50), nullable=False)  # critical, high, medium, low
    steps_to_reproduce = Column(Text, nullable=False)
    expected = Column(Text, nullable=False)
    actual = Column(Text, nullable=False)
    screenshot_url = Column(String(500), nullable=True)
    status = Column(String(50), nullable=False, default="open")  # open, retested, closed
    due_date = Column(DateTime, nullable=True)
    is_blocked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="defects")
    test_run = relationship("TestRun", back_populates="defects")
    owner = relationship("User", foreign_keys=[owner_id], back_populates="defects")


# ==============================================================================
# Asma Module (Marketing)
# ==============================================================================

class BrandProfile(Base):
    __tablename__ = "brand_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    brand_name = Column(String(255), nullable=False)
    brand_voice = Column(Text, nullable=True)
    target_audience = Column(Text, nullable=True)
    required_wording = Column(Text, nullable=True)
    prohibited_wording = Column(Text, nullable=True)
    contact_details = Column(Text, nullable=True)
    languages = Column(Text, nullable=True)
    client_rules = Column(Text, nullable=True)
    version_number = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="brand_profiles")
    client = relationship("Client", back_populates="brand_profiles")
    campaign_briefs = relationship("CampaignBrief", back_populates="brand_profile", cascade="all, delete-orphan")


class CampaignBrief(Base):
    __tablename__ = "campaign_briefs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    brand_profile_id = Column(UUID(as_uuid=True), ForeignKey("brand_profiles.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    audience = Column(Text, nullable=True)
    location = Column(Text, nullable=True)
    offer = Column(Text, nullable=True)
    dates = Column(Text, nullable=True)
    deliverables = Column(Text, nullable=True)
    platforms = Column(Text, nullable=True)
    assets = Column(Text, nullable=True)
    source_message_ids = Column(JSON, nullable=True)
    missing_fields = Column(JSON, nullable=True)
    approval_status = Column(String(50), default="pending", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="campaign_briefs")
    brand_profile = relationship("BrandProfile", back_populates="campaign_briefs")
    calendar_items = relationship("CalendarItem", back_populates="campaign_brief", cascade="all, delete-orphan")


class CalendarItem(Base):
    __tablename__ = "calendar_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    campaign_brief_id = Column(UUID(as_uuid=True), ForeignKey("campaign_briefs.id", ondelete="CASCADE"), nullable=True)
    scheduled_time = Column(DateTime, nullable=False)
    content_draft = Column(Text, nullable=True)
    platform = Column(String(100), nullable=True)
    objective = Column(Text, nullable=True)
    status = Column(String(50), nullable=True)
    owner = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="calendar_items")
    campaign_brief = relationship("CampaignBrief", back_populates="calendar_items")


class DesignerBrief(Base):
    __tablename__ = "designer_briefs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True)
    content_version_id = Column(UUID(as_uuid=True), ForeignKey("content_versions.id", ondelete="CASCADE"), nullable=True)
    main_heading = Column(String(255), nullable=True)
    supporting_text = Column(Text, nullable=True)
    cta = Column(Text, nullable=True)
    visual_direction = Column(Text, nullable=True)
    asset_references = Column(Text, nullable=True)
    sizes = Column(Text, nullable=True)
    logo_qr_rules = Column(Text, nullable=True)
    restrictions = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="designer_briefs")
    campaign = relationship("Campaign")
    content_version = relationship("ContentVersion")


# ==============================================================================
# Vishaqa Module (Support Intelligence)
# ==============================================================================

class TicketTaxonomy(Base):
    __tablename__ = "ticket_taxonomy"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(255), nullable=False)
    confidence_threshold = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Extended fields for DB-versioned classification rules
    product = Column(String(255), nullable=False)
    severity = Column(String(50), nullable=False)
    owner_team = Column(String(255), nullable=False)
    human_required = Column(Boolean, default=False, nullable=False)
    rules_definition = Column(JSON, nullable=True)
    priority = Column(Integer, default=100, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="ticket_taxonomies")



class KBArticle(Base):
    __tablename__ = "kb_articles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    review_status = Column(String(50), default="draft", nullable=False)
    product = Column(String(100), nullable=True)
    risk_level = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="kb_articles")
    chunks = relationship("KBArticleChunk", back_populates="kb_article", cascade="all, delete-orphan")



class KBArticleChunk(Base):
    __tablename__ = "kb_article_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_article_id = Column(UUID(as_uuid=True), ForeignKey("kb_articles.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_content = Column(Text, nullable=False)
    vector_embedding = Column(Text, nullable=True)  # JSON or serialized format
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    kb_article = relationship("KBArticle", back_populates="chunks")


class AIRun(Base):
    __tablename__ = "ai_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    run_type = Column(String(100), nullable=False)  # e.g., classify, summarize, retrieve, suggest-reply, escalation
    status = Column(String(50), default="pending")  # pending, success, failed
    input_data = Column(Text, nullable=True)
    output_data = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="ai_runs")


class TicketPrediction(Base):
    __tablename__ = "ticket_predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    corrected_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    client_room_id = Column(UUID(as_uuid=True), ForeignKey("client_rooms.id", ondelete="CASCADE"), nullable=True)  # TODO: migrate this FK to tickets table once tickets are implemented
    predicted_category = Column(String(255), nullable=False)
    actual_category = Column(String(255), nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="ticket_predictions")
    corrected_by = relationship("User", back_populates="corrected_predictions")
    client_room = relationship("ClientRoom")


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    client_room_id = Column(UUID(as_uuid=True), ForeignKey("client_rooms.id", ondelete="CASCADE"), nullable=False)
    reviewer_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    summary_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="conversation_summaries")
    client_room = relationship("ClientRoom")
    reviewer = relationship("User", back_populates="reviewed_summaries")

class MediaAsset(Base):
    __tablename__ = "media_assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=True)
    file_url = Column(Text, nullable=False)  # signed media URL or data URL
    version_number = Column(Integer, nullable=False, default=1)
    is_locked = Column(Boolean, default=False)
    status = Column(String(50), default="pending_review")  # pending_review, approved, rejected
    reviewed_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class SocialAccount(Base):
    __tablename__ = "social_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    platform = Column(String(50), nullable=False)  # Instagram, Facebook, TikTok, LinkedIn
    account_identifier = Column(String(255), nullable=False)  # username/handle
    access_token_encrypted = Column(Text, nullable=False)
    status = Column(String(50), default="connected")  # connected, disconnected, token_expired
    connected_at = Column(DateTime, default=datetime.utcnow)