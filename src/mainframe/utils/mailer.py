"""Sending emails"""

from msgraph.core import GraphClient


def _build_formatted_recipients_list(
    recipient_addresses: list[str] | None,
) -> list[dict[str, dict[str, str]]]:
    """Build a list of recipient addresses"""
    if recipient_addresses is None:
        return []
    return [{"emailAddress": {"address": recipient_address}} for recipient_address in recipient_addresses]


def send_email(
    graph_client: GraphClient,  # type: ignore
    sender: str,
    subject: str,
    content: str,
    reply_to_recipients: list[str] | None = None,
    to_recipients: list[str] | None = None,
    cc_recipients: list[str] | None = None,
    bcc_recipients: list[str] | None = None,
) -> None:
    """Send an email"""
    data = {
        "message": {
            "subject": subject,
            "body": {"contentType": "text", "content": content},
        },
    }

    recipients_groups = [
        ("replyTo", reply_to_recipients),
        ("toRecipients", to_recipients),
        ("ccRecipients", cc_recipients),
        ("bccRecipients", bcc_recipients),
    ]
    for recipients_type, recipients_list in recipients_groups:
        if recipients_list is not None:
            data[recipients_type] = _build_formatted_recipients_list(
                recipients_list)

    graph_client.post(url=f"/users/{sender}/sendMail", json=data)  # type: ignore
