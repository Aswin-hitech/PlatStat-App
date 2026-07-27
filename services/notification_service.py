import logging
from repositories import NotificationRepository

logger = logging.getLogger("platstat.notifications")
notification_repo = NotificationRepository()


class BaseNotificationProvider:
    """Interface for notification channels (In-App, Email, Webhook, Discord, etc.)."""
    def send(self, user_id, title, message, contest_id=None, n_type="reminder"):
        raise NotImplementedError


class InAppNotificationProvider(BaseNotificationProvider):
    def send(self, user_id, title, message, contest_id=None, n_type="reminder"):
        return notification_repo.create_notification(
            user_id=user_id,
            title=title,
            message=message,
            contest_id=contest_id,
            n_type=n_type
        )


class EmailNotificationProvider(BaseNotificationProvider):
    """Extensible provider for Email notifications."""
    def send(self, user_id, title, message, contest_id=None, n_type="reminder"):
        logger.info("[EmailProvider] (Future Integration) Sending email to user %s: %s", user_id, title)
        return True


class WebhookNotificationProvider(BaseNotificationProvider):
    """Extensible provider for Webhook / Discord / Telegram notifications."""
    def send(self, user_id, title, message, contest_id=None, n_type="reminder"):
        logger.info("[WebhookProvider] (Future Integration) Webhook alert for user %s: %s", user_id, title)
        return True


class NotificationManager:
    """Future-ready notification service managing multiple providers."""
    def __init__(self):
        self.providers = [
            InAppNotificationProvider(),
            EmailNotificationProvider(),
            WebhookNotificationProvider(),
        ]

    def send_notification(self, user_id, title, message, contest_id=None, n_type="reminder"):
        results = []
        for provider in self.providers:
            try:
                res = provider.send(user_id, title, message, contest_id=contest_id, n_type=n_type)
                results.append(res)
            except Exception as e:
                logger.error("Provider %s failed: %s", provider.__class__.__name__, e)
        return results

    def get_user_notifications(self, user_id="default_user", limit=50):
        items, unread = notification_repo.get_user_notifications(user_id=user_id, limit=limit)
        return items, unread

    def mark_read(self, user_id, notification_id):
        return notification_repo.mark_as_read(user_id, notification_id)

    def clear_all(self, user_id="default_user"):
        return notification_repo.clear_all(user_id)


notification_manager = NotificationManager()
