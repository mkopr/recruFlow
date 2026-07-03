import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes.health import router as health_router
from app.api.routes.ingestion import router as ingestion_router
from app.api.routes.offers import router as offers_router
from app.api.routes.scheduler import router as scheduler_router
from app.config import get_settings
from app.db.session import get_engine, get_sessionmaker
from app.scheduler.lifecycle import register_jobs
from app.scheduler.service import ensure_sources_exist

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)

    async with sessionmaker() as session:
        await ensure_sources_exist(session)
        await session.commit()

    scheduler = AsyncIOScheduler(timezone="UTC")
    job_count = await register_jobs(scheduler, sessionmaker)
    scheduler.start()
    logger.info("scheduler started with %d job(s)", job_count)
    app.state.scheduler = scheduler

    try:
        yield
    finally:
        scheduler.shutdown(wait=True)
        await engine.dispose()
        logger.info("scheduler shut down")


settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(title="recruFlow API", version=__version__, lifespan=lifespan)
app.state.settings = settings

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_allow_origin],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(scheduler_router)
app.include_router(ingestion_router)
app.include_router(offers_router)
