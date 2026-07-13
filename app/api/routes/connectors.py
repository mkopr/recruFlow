from fastapi import APIRouter

from app.ingestion.registry import CONNECTOR_REGISTRY
from app.schemas.connectors import ConnectorOption

router = APIRouter()


@router.get("/connectors")
async def list_connectors() -> list[ConnectorOption]:
    return [ConnectorOption(id=spec.name, label=spec.label) for spec in CONNECTOR_REGISTRY.values()]
