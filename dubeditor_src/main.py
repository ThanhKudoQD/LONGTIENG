from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

from database import init_db
from routers import projects, subtitles, characters, tts, export, ws

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    os.makedirs("../storage/videos", exist_ok=True)
    os.makedirs("../storage/audio", exist_ok=True)
    os.makedirs("../storage/exports", exist_ok=True)
    os.makedirs("../storage/projects", exist_ok=True)
    yield

app = FastAPI(title="DubEditor API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router,   prefix="/api/projects",   tags=["projects"])
app.include_router(subtitles.router,  prefix="/api/subtitles",  tags=["subtitles"])
app.include_router(characters.router, prefix="/api/characters", tags=["characters"])
app.include_router(tts.router,        prefix="/api/tts",        tags=["tts"])
app.include_router(export.router,     prefix="/api/export",     tags=["export"])
app.include_router(ws.router,         tags=["websocket"])

app.mount("/storage", StaticFiles(directory="../storage"), name="storage")
