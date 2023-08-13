"""Receives messages over the results AMQP queue and adds it to the database"""

import json
from datetime import datetime, timezone

import pika
from pika.channel import Channel
from pika.spec import Basic, BasicProperties
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mainframe.constants import mainframe_settings
from mainframe.database import sessionmaker
from mainframe.models.orm import Rule, Scan
from mainframe.models.schemas import PackageScanResult


def handle_delivery(body: bytes) -> None:
    results = PackageScanResult(**json.loads(body))
    with sessionmaker() as session:
        row = Scan(
            name=results.name,
            version=results.version,
            score=results.score,
            inspector_url=results.inspector_url,
            rules=[],  # this will be filled in later
            finished_at=datetime.now(tz=timezone.utc),
        )

        # These are the rules that already have an entry in the database
        rules = session.scalars(select(Rule).where(Rule.name.in_(results.rules_matched))).all()
        row.rules.extend(rules)
        existing_rule_names = {rule.name for rule in rules}

        # These are the rules that had to be created
        new_rules = [
            Rule(name=rule_name) for rule_name in results.rules_matched if rule_name not in existing_rule_names
        ]
        row.rules.extend(new_rules)

        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            pass


def target():
    connection = pika.BlockingConnection(pika.URLParameters(mainframe_settings.amqp_connection_string))
    channel = connection.channel()
    channel.queue_declare(queue="results")  # pyright: ignore

    def callback(channel: Channel, method: Basic.Deliver, _: BasicProperties, body: bytes):
        try:
            handle_delivery(body)
        except:
            channel.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
            raise
        else:
            channel.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_consume(queue="results", on_message_callback=callback)  # pyright: ignore

    channel.start_consuming()
