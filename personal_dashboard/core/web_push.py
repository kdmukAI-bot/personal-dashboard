from __future__ import annotations

import asyncio
import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select

from personal_dashboard.config import settings
from personal_dashboard.core.sse import sse_bus
from personal_dashboard.database import get_core_db_context
from personal_dashboard.models.notification import Notification
from personal_dashboard.models.subscription import PushSubscription

logger = logging.getLogger(__name__)


def _send_one(sub_info: dict, payload: str) -> None:
    webpush(
        subscription_info=sub_info,
        data=payload,
        vapid_private_key=settings.vapid_private_key,
        vapid_claims={"sub": settings.vapid_subject},
    )


async def dispatch(
    title: str,
    body: str | None = None,
    *,
    image_url: str | None = None,
    click_url: str | None = None,
    source: str | None = None,
) -> tuple[int, int]:
    payload = json.dumps(
        {
            "title": title,
            "body": body,
            "image": image_url,
            "click_url": click_url,
            "source": source,
        }
    )

    delivered = 0
    failed = 0
    stale_endpoints: list[str] = []

    async with get_core_db_context() as db:
        result = await db.scalars(select(PushSubscription))
        subs = list(result.all())

    for sub in subs:
        sub_info = {
            "endpoint": sub.endpoint,
            "keys": {"p256dh": sub.p256dh_key, "auth": sub.auth_key},
        }
        try:
            await asyncio.to_thread(_send_one, sub_info, payload)
            delivered += 1
        except WebPushException as exc:
            failed += 1
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None) if response is not None else None
            if status_code in (404, 410):
                stale_endpoints.append(sub.endpoint)
            else:
                logger.warning("webpush failed for %s: %s", sub.endpoint, exc)
        except Exception as exc:
            failed += 1
            logger.exception("unexpected webpush error for %s: %s", sub.endpoint, exc)

    async with get_core_db_context() as db:
        if stale_endpoints:
            await db.execute(
                delete(PushSubscription).where(PushSubscription.endpoint.in_(stale_endpoints))
            )

        notif = Notification(
            title=title,
            body=body,
            image_url=image_url,
            click_url=click_url,
            source=source,
            delivered_count=delivered,
            failed_count=failed,
        )
        db.add(notif)
        await db.commit()
        await db.refresh(notif)

        sse_bus.publish(
            "notification",
            {
                "id": notif.id,
                "title": notif.title,
                "body": notif.body,
                "source": notif.source,
                "sent_at": notif.sent_at.isoformat() if notif.sent_at else None,
            },
        )

    return delivered, failed
