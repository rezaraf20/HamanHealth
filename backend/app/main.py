from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import Base, engine
from .routers import auth, sessions
from .routers import dashboard
from .routers import admin
from .routers import consent
from .routers import timeline
from .routers import account
from .routers import records

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on first run (use Alembic in production for migrations)
    Base.metadata.create_all(bind=engine)
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


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "haman-health-api"}
