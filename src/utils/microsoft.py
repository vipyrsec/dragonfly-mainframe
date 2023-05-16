"""Microsoft auth integration"""

from os import getenv

from azure.identity import ClientSecretCredential
from dotenv import load_dotenv
from msgraph.core import GraphClient

load_dotenv()

tenant_id = getenv("MICROSOFT_TENANT_ID")
client_id = getenv("MICROSOFT_CLIENT_ID")
client_secret = getenv("MICROSOFT_CLIENT_SECRET")

assert tenant_id is not None
assert client_id is not None
assert client_secret is not None


def build_ms_graph_client() -> GraphClient:
    """Build authenticated GraphClient"""
    client_secret_credential = ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )
    return GraphClient(credential=client_secret_credential)
