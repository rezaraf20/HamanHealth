from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import auth, sessions
from .routers import dashboard
from .routers import admin
from .routers import consent
from .routers import timeline
from .routers import account
from .routers import records
from .routers import clips
from .routers import observations

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tables are created and updated by Alembic migrations, run before the server
    # starts (see docker-entrypoint.sh). create_all can only add missing tables, never
    # change existing ones, so it would hide a schema that is out of date.
    yield


app = FastAPI(
    title="Haman Health API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(consent.router)
app.include_router(timeline.router)
app.include_router(account.router)
app.include_router(records.router)
app.include_router(clips.router)
app.include_router(observations.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "haman-health-api"}
