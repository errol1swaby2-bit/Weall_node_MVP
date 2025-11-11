#!/usr/bin/env python3
"""
Content API (IPFS upload + simple text feed)
- POST /content/upload  (existing)
- POST /content/post    -> store small text posts
- GET  /content/feed    -> list recent posts
"""
import os, time, logging, uuid
from typing import List, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from weall_node.weall_runtime.storage import get_client
from weall_node.settings import Settings as S
from ..weall_executor import executor

router = APIRouter(prefix="/content", tags=["content"])
log = logging.getLogger("content")
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )


# ---------- Feed storage helpers ----------
def _posts() -> List[dict]:
    return executor.ledger.setdefault("posts", [])


def _append_post(p: dict):
    p = dict(p)
    p.setdefault("id", str(uuid.uuid4()))
    p.setdefault("ts", int(time.time()))
    _posts().append(p)
    executor.save_state()
    return p


# ---------- Models ----------
class NewPost(BaseModel):
    author: str
    text: str
    tags: Optional[List[str]] = None


# ---------- Upload (existing) ----------
@router.post("/upload")
async def upload_content(
    file: UploadFile = File(...), visibility: str = Form("private")
):
    try:
        data = await file.read()
        if len(data) > S.MAX_UPLOAD_SIZE:
            raise HTTPException(413, f"File too large. Max {S.MAX_UPLOAD_SIZE} bytes")

        ipfs = get_client()
        filename = os.path.basename(file.filename)

        if ipfs:
            try:
                cid = ipfs.add_bytes(data)
                log.info("IPFS upload success: %s -> CID %s", filename, cid)
                return {
                    "success": True,
                    "cid": cid,
                    "filename": filename,
                    "bytes": len(data),
                    "visibility": visibility,
                    "ipfs_stored": True,
                    "mime": file.content_type,
                }
            except Exception as e:
                log.warning("IPFS upload failed for %s: %s", filename, e)

        ts = int(time.time())
        out_dir = getattr(S, "LOCAL_UPLOAD_DIR", ".uploads")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{ts}_{filename}")
        with open(out_path, "wb") as f:
            f.write(data)

        fake_cid = f"local-{ts}-{filename}"
        log.info("Fallback upload stored: %s -> %s", filename, out_path)
        return {
            "success": True,
            "cid": fake_cid,
            "filename": filename,
            "bytes": len(data),
            "path": out_path,
            "visibility": visibility,
            "ipfs_stored": False,
            "mime": file.content_type,
        }
    except HTTPException:
        raise
    except Exception as e:
        fake_cid = f"failed-{int(time.time())}-{os.path.basename(file.filename)}"
        log.error("Upload failed for %s: %s", file.filename, e)
        return JSONResponse(
            status_code=500,
            content={"success": False, "cid": fake_cid, "error": str(e)},
        )


# ---------- New: text posts ----------
@router.post("/post")
def create_post(body: NewPost):
    text = (body.text or "").strip()
    if not body.author or not text:
        raise HTTPException(400, "author and text are required")
    if len(text) > 2000:
        raise HTTPException(400, "text is too long")
    p = _append_post({"author": body.author, "text": text, "tags": body.tags or []})
    return {"ok": True, "post": p}


@router.get("/feed")
def feed():
    # newest first
    items = list(reversed(_posts()))[:200]
    return items
