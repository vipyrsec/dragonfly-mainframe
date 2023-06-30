"""Microsoft auth integration"""

from azure.identity import ClientSecretCredential
from msgraph.core import GraphClient  # type: ignore

from mainframe.constants import microsoft_settings


def build_ms_graph_client() -> GraphClient:  # type: ignore
    """Build authenticated GraphClient"""
    client_secret_credential = ClientSecretCredential(
        tenant_id=microsoft_settings.tenant_id,
        client_id=microsoft_settings.client_id,
        client_secret=microsoft_settings.client_secret,
    )
    return GraphClient(credential=client_secret_credential)  # type: ignore
