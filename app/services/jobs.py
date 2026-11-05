import logging

from apscheduler.schedulers.background import BackgroundScheduler

from . import publishing, subscriptions

log = logging.getLogger(__name__)


def start_scheduler(app):
    def publish_job():
        with app.app_context():
            try:
                publishing.publish_due_blogs()
            except Exception:
                log.exception("Scheduled publishing job failed")

    def expire_job():
        with app.app_context():
            try:
                subscriptions.expire_overdue()
            except Exception:
                log.exception("Subscription expiry job failed")

    scheduler = BackgroundScheduler(timezone="UTC", daemon=True)
    scheduler.add_job(publish_job, "interval", minutes=1, max_instances=1, coalesce=True)
    scheduler.add_job(expire_job, "interval", hours=1, max_instances=1, coalesce=True)
    scheduler.start()
    return scheduler
