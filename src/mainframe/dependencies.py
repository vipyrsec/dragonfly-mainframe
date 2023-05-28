from functools import cache

from msgraph.core import GraphClient

from mainframe.utils.microsoft import build_ms_graph_client


@cache
def get_ms_graph_client() -> GraphClient:
    return build_ms_graph_client()
