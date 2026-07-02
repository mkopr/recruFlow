from fastapi import FastAPI

from app import __version__
from app.api.routes.health import router as health_router
from app.config import get_settings

settings = get_settings()

app = FastAPI(title="recruFlow API", version=__version__)
app.state.settings = settings

app.include_router(health_router)
