"""License API endpoints (public — không cần middleware check)."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dubeditor import license_service

router = APIRouter()


class ActivateRequest(BaseModel):
    key: str


@router.get("/status")
def get_status():
    """Trả về trạng thái license hiện tại (có hợp lệ không, còn bao ngày...)."""
    return license_service.get_status()


@router.get("/machine-id")
def get_machine_id():
    """Trả machine ID — user gửi cho admin để xin key."""
    return {"machine_id": license_service.get_machine_id()}


@router.post("/activate")
def activate(req: ActivateRequest):
    """User nhập key → verify + lưu local."""
    result = license_service.activate(req.key)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return result["info"]


@router.post("/deactivate")
def deactivate():
    """Xóa license (đổi key)."""
    ok = license_service.deactivate()
    return {"ok": ok}
