"""Routers de la API. Cada módulo agrupa los endpoints de un dominio."""

from fastapi import APIRouter

from . import altas, inventory, network, operations, reservations, system

api_router = APIRouter()
for module in (system, inventory, network, reservations, altas, operations):
    api_router.include_router(module.router)
