#!/usr/bin/env python3
"""
Content Upload API (IPFS + Local Fallback)
------------------------------------------
Handles user content uploads securely with size limits and optional IPFS pinning.

Features:
- Validates file size against S.MAX_UPLOAD_SIZE
- Attempts IPFS first, then falls back to local .uploads/ folder
- Returns consistent response schema for frontend compatibility
"""

import os, time, logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse
from weall_node.weall_runtime.storage import get_client
from weall_node.settings import Settings as S

router = APIRouter(prefix="/content", tags=["content"])
logger = logging.getLogger("content")

if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


@router.post("/upload")
async def upload_content(
    request: Request,
    file: UploadFile = File(...),
    visibility: str = Form("private")
):
    """Accepts file uploads, stores on IPFS if available, and falls back to local disk."""
    try:
        data = await file.read()
        if len(data) > S.MAX_UPLOAD_SIZE:
            raise HTTPException(413, f"File too large. Max {S.MAX_UPLOAD_SIZE} bytes")

        ipfs = get_client()
        filename = os.path.basename(file.filename)

        # --- Try IPFS first ---
        if ipfs:
            try:
                cid = ipfs.add_bytes(data)
                logger.info("IPFS upload success: %s -> CID %s", filename, cid)
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
                logger.warning("IPFS upload failed for %s: %s", filename, e)

        # --- Local fallback ---
        ts = int(time.time())
        out_dir = getattr(S, "LOCAL_UPLOAD_DIR", ".uploads")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{ts}_{filename}")
        with open(out_path, "wb") as f:
            f.write(data)

        fake_cid = f"local-{ts}-{filename}"
        logger.info("Fallback upload stored: %s -> %s", filename, out_path)
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
        raise  # Let FastAPI handle HTTP errors cleanly

    except Exception as e:
        fake_cid = f"failed-{int(time.time())}-{os.path.basename(file.filename)}"
        logger.error("Upload failed for %s: %s", file.filename, e)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "cid": fake_cid,
                "error": str(e),
            },
        )
