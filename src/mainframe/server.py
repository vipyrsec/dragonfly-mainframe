from fastapi import FastAPI

from mainframe.endpoints import routers

app = FastAPI()

for router in routers:
    app.include_router(router)
