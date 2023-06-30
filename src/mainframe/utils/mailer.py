"""Sending emails"""

from msgraph.core import GraphClient  # type: ignore


def _build_recipients_list_ms(
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
    to_recipients: list[str],
    cc_recipients: list[str] | None,
    bcc_recipients: list[str] | None,
) -> None:
    """Send an email"""
    data = {
        "message": {
            "subject": subject,
            "body": {"contentType": "text", "content": content},
            "toRecipients": _build_recipients_list_ms(to_recipients),
            "ccRecipients": _build_recipients_list_ms(cc_recipients),
            "bccRecipients": _build_recipients_list_ms(bcc_recipients),
        },
    }

    graph_client.post(url=f"/users/{sender}/sendMail", json=data)  # type: ignore
