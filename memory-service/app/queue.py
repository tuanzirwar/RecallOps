from __future__ import annotations

import json
import logging
import time

import pika
from sqlalchemy import select

from .config import get_settings
from .database import SessionLocal
from .extraction import process_task
from .models import OutboxEvent

QUEUE = "recallops.extract.v1"
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def connection():
    return pika.BlockingConnection(pika.URLParameters(get_settings().rabbitmq_url))


def publish_once() -> int:
    with SessionLocal() as db:
        events = db.scalars(select(OutboxEvent).where(OutboxEvent.status == "pending").order_by(OutboxEvent.created_at).limit(20)).all()
        if not events:
            return 0
        conn = connection()
        try:
            channel = conn.channel()
            channel.queue_declare(queue=QUEUE, durable=True)
            channel.confirm_delivery()
            for event in events:
                channel.basic_publish(
                    exchange="", routing_key=QUEUE,
                    body=json.dumps({"task_id": event.task_id}).encode(),
                    properties=pika.BasicProperties(delivery_mode=2, message_id=event.id, content_type="application/json"),
                    mandatory=True,
                )
                event.status = "published"
                db.commit()
            return len(events)
        finally:
            conn.close()


def publisher_main() -> None:
    while True:
        try:
            if not publish_once():
                time.sleep(1)
        except Exception:
            log.exception("outbox publish failed; pending events will retry")
            time.sleep(2)


def worker_main() -> None:
    while True:
        try:
            conn = connection()
            channel = conn.channel()
            channel.queue_declare(queue=QUEUE, durable=True)
            channel.basic_qos(prefetch_count=1)

            def on_message(ch, method, properties, body):
                try:
                    task_id = json.loads(body)["task_id"]
                    with SessionLocal() as db:
                        status = process_task(db, task_id)
                    log.info("task %s ended %s", task_id, status)
                    if status == "queued":
                        time.sleep(2)
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    else:
                        ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception:
                    log.exception("worker interrupted; message will be redelivered")
                    raise

            channel.basic_consume(queue=QUEUE, on_message_callback=on_message, auto_ack=False)
            channel.start_consuming()
        except Exception:
            log.exception("worker connection lost; retrying")
            time.sleep(2)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2 or sys.argv[1] not in {"publisher", "worker"}:
        raise SystemExit("usage: python -m app.queue publisher|worker")
    (publisher_main if sys.argv[1] == "publisher" else worker_main)()
