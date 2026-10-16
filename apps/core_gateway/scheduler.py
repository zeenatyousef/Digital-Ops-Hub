import time
import threading
import json
import random
from datetime import datetime
from sqlalchemy.orm import Session
import logging

from packages.database.session import SessionLocal
from packages.database.models import PublishingJob, Campaign, AnalyticsEvent

# Set up logging for scheduler
logger = logging.getLogger("scheduler")
logger.setLevel(logging.INFO)

# Global shutdown event to clean up thread on app exit
shutdown_event = threading.Event()
scheduler_thread = None

def process_queued_jobs():
    db: Session = SessionLocal()
    try:
        now = datetime.utcnow()
        # Find all queued jobs that are scheduled to publish now or in the past
        jobs = db.query(PublishingJob).filter(
            PublishingJob.status == "queued",
            PublishingJob.scheduled_at <= now
        ).all()
        
        for job in jobs:
            logger.info(f"Scheduler processing job {job.id} for campaign {job.campaign_id}")
            job.status = "processing"
            db.commit()
            
            # Fetch campaign to check simulation rules
            campaign = db.query(Campaign).filter(Campaign.id == job.campaign_id).first()
            campaign_name = campaign.name.lower() if campaign else ""
            
            # Simulation rules:
            # 1. If campaign name contains "fail", it fails completely and sets to failed/manual_handoff
            # 2. If campaign name contains "retry" and retry_count < 2, it fails with retry (status -> queued)
            # 3. Otherwise, it succeeds
            
            if "fail" in campaign_name:
                job.retry_count += 1
                job.error_logs = f"Failed to publish: simulated network integration timeout (attempt {job.retry_count})"
                if job.retry_count >= 3:
                    job.status = "failed" # Final failure
                else:
                    job.status = "queued" # Put back in queue to retry
                logger.info(f"Job {job.id} failed. Status: {job.status}, retry: {job.retry_count}")
                
            elif "retry" in campaign_name and job.retry_count < 2:
                job.retry_count += 1
                job.error_logs = f"Temporary publication failure, scheduling retry (attempt {job.retry_count})"
                job.status = "queued"
                logger.info(f"Job {job.id} retrying. Status: queued, retry: {job.retry_count}")
                
            else:
                # Success - mark job completed
                job.status = "completed"
                job.completed_at = datetime.utcnow()
                if campaign:
                    remaining_jobs = db.query(PublishingJob).filter(
                        PublishingJob.campaign_id == campaign.id,
                        PublishingJob.id != job.id,
                        PublishingJob.status.in_(["queued", "processing", "failed"])
                    ).count()

                    # Rule 3: No campaign marked published without platform confirmation (platform_post_id) or manual proof (manual_proof)
                    has_proof = bool(job.platform_post_id or job.manual_proof)
                    if has_proof:
                        if remaining_jobs == 0:
                            campaign.status = "published"
                        else:
                            campaign.status = "partially_published"

                    # NOTE: No live social platform integration yet (known limitation).
                    # Plausible simulated engagement numbers for Esha analytics service
                    simulated_reach = random.randint(500, 5000)
                    simulated_engagement_pct = round(random.uniform(3.0, 9.5), 1)
                    simulated_engagement = int(simulated_reach * (simulated_engagement_pct / 100))

                    analytics_event = AnalyticsEvent(
                        tenant_id=campaign.tenant_id,
                        client_id=campaign.client_id,
                        event_type="post.published",
                        object_type="campaign",
                        object_id=campaign.id,
                        source="scheduler (simulated — no live platform integration yet)",
                        occurred_at=datetime.utcnow(),
                        idempotency_key=f"pub-completed-{job.id}",
                        event_data=json.dumps({"job_id": str(job.id), "campaign_name": campaign.name}),
                        metrics=json.dumps({
                            "reach": simulated_reach,
                            "engagement": simulated_engagement,
                            "engagement_pct": simulated_engagement_pct
                        })
                    )
                    db.add(analytics_event)

                logger.info(f"Job {job.id} successfully completed and published!")
                
            db.commit()
            
    except Exception as e:
        logger.error(f"Error in scheduler process run: {str(e)}")
    finally:
        db.close()

def scheduler_loop():
    logger.info("Background scheduler daemon loop started.")
    while not shutdown_event.is_set():
        process_queued_jobs()
        # Sleep in short increments to respond quickly to shutdown
        for _ in range(50):
            if shutdown_event.is_set():
                break
            time.sleep(0.1)
    logger.info("Background scheduler daemon loop stopped.")

def start_scheduler():
    global scheduler_thread, shutdown_event
    shutdown_event.clear()
    scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    scheduler_thread.start()

def stop_scheduler():
    global shutdown_event, scheduler_thread
    shutdown_event.set()
    if scheduler_thread:
        scheduler_thread.join(timeout=2.0)
