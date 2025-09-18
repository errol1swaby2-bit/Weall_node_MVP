# api/pinning.py
from fastapi import APIRouter

router = APIRouter(prefix="/pinning", tags=["Pinning / Storage"])

pinned_files = []

@router.post("/pin")
def pin(file_hash: str):
    if file_hash not in pinned_files:
        pinned_files.append(file_hash)
    return {"ok": True, "pinned": pinned_files}

@router.get("/")
def list_pins():
    return {"pinned": pinned_files}
