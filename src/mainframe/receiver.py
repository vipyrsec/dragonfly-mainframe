"""Receives messages over the results AMQP queue and adds it to the database"""

import json
from datetime import datetime, timezone

import aio_pika
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

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


async def task(amqp_url: str):
    connection = await aio_pika.connect_robust(amqp_url)
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(name="results", durable=True)

        async with queue.iterator() as queue_iterator:
            async for message in queue_iterator:
                async with message.process(requeue=False):
                    handle_delivery(message.body)
