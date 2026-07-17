from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db
from app.routers import health, detect, detect_image, auth

app = FastAPI(title=settings.APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(detect.router)
app.include_router(detect_image.router)

# Clean page routes. These are declared before the StaticFiles mount below,
# so they take priority over it - the mount only ever handles paths none
# of these matched (plus serving these same files directly by filename,
# e.g. /login.html still works as a fallback).
STATIC_DIR = "app/static"


@app.get("/", include_in_schema=False)
def serve_landing():
    return FileResponse(f"{STATIC_DIR}/landing.html")


@app.get("/app", include_in_schema=False)
def serve_app():
    # Auth itself is enforced client-side (redirects to /login without a
    # token) and server-side on every /api/detect* call via require_quota -
    # this route just serves the shell.
    return FileResponse(f"{STATIC_DIR}/index.html")


@app.get("/login", include_in_schema=False)
def serve_login():
    return FileResponse(f"{STATIC_DIR}/login.html")


@app.get("/signup", include_in_schema=False)
def serve_signup():
    return FileResponse(f"{STATIC_DIR}/signup.html")


# Fallback for any other static asset under app/static (images, etc. if
# added later), and for the .html files directly by name.
app.mount("/static", StaticFiles(directory=STATIC_DIR, html=True), name="static")

