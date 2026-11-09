from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import Base, SessionLocal, engine
from .errors import WMSError
from .routers import auth, config_routes, counts, dashboard, inbound, inventory, items, outbound, tasks
from .seed import seed


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Creates any missing tables. For production schema changes, add Alembic migrations.
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
        db.commit()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan,
              description="Generic warehouse management system API. Interactive docs at /docs.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(WMSError)
async def wms_error_handler(_: Request, exc: WMSError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


for r in (auth, config_routes, items, inventory, inbound, outbound, tasks, counts, dashboard):
    app.include_router(r.router, prefix="/api")


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok"}


# Serve the built React GUI (frontend/dist) from the same origin.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = DIST / path
        if path and candidate.is_file() and DIST in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
