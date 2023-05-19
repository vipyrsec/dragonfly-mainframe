from importlib import import_module
from pkgutil import walk_packages

from fastapi import APIRouter

from mainframe import endpoints

routers: list[APIRouter] = []
for module_info in walk_packages(endpoints.__path__, f"{endpoints.__name__}."):
    module = import_module(module_info.name)
    router = getattr(module, "router", None)
    if router is not None:
        routers.append(router)
