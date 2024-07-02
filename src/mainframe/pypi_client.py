from functools import cache
from typing import Annotated, Generator

from fastapi import Depends
from httpx import Response, Auth, Request, AsyncClient
from fastapi.encoders import jsonable_encoder

from mainframe.constants import pypi
from mainframe.models.schemas import Observation


class ObservationFailure(Exception):
    def __init__(self, response: Response) -> None:
        self.response = response


class BearerAuthenticator(Auth):
    def __init__(self, *, token: str) -> None:
        self.token = token

    def auth_flow(self, request: Request) -> Generator[Request, Response, None]:
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


class PyPiClient:
    def __init__(self) -> None:
        auth = BearerAuthenticator(token="token")
        headers = {"Content-Type": "application/vnd.pypi.api-v0-danger+json"}
        self.client = AsyncClient(auth=auth, headers=headers, base_url=pypi.pypi_base_url)

    async def echo(self) -> str:
        response = await self.client.get("/echo")
        json = response.json()
        return json["username"]

    async def send_observation(self, package_name: str, observation: Observation) -> None:
        path = f"/packages/{package_name}/observations"
        data = jsonable_encoder(observation)

        response = await self.client.post(path, json=data)
        try:
            response.raise_for_status()
        except Exception as e:
            raise ObservationFailure(response) from e


@cache
async def get_pypi_report_client() -> PyPiClient:
    return PyPiClient()


PyPIClientDependency = Annotated[PyPiClient, Depends(get_pypi_report_client)]
