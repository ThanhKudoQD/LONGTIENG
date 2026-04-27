from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from collections import defaultdict
import json

router = APIRouter()
_connections: dict = defaultdict(set)

@router.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: int):
    await websocket.accept()
    _connections[project_id].add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _connections[project_id].discard(websocket)

async def broadcast(project_id: int, message: dict):
    dead = set()
    for ws in _connections.get(project_id, set()):
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.add(ws)
    for ws in dead:
        _connections[project_id].discard(ws)
