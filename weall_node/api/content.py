from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse
import os, time, logging
from weall_node.weall_runtime.storage import get_client
from weall_node.settings import Settings as S

router = APIRouter(prefix="/content", tags=["content"])
logger = logging.getLogger("content")

@router.post("/upload")
async def upload_content(
    request: Request,
    file: UploadFile = File(...),
    visibility: str = Form("private")
):
    try:
        data = await file.read()
        if len(data) > S.MAX_UPLOAD_SIZE:
            raise HTTPException(413, f"File too large. Max {S.MAX_UPLOAD_SIZE} bytes")

        ipfs = get_client()
        if ipfs:
            try:
                cid = ipfs.add_bytes(data)
                logger.info("Uploaded %s -> CID %s", file.filename, cid)
                return {
                    "ok": True,
                    "cid": cid,
                    "bytes": len(data),
                    "visibility": visibility,
                    "ipfs": True,
                }
            except Exception as e:
                logger.warning("IPFS add failed for %s: %s", file.filename, e)

        # ---- fallback path (always returns CID) ----
        ts = int(time.time())
        out_dir = ".uploads"
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{ts}_{file.filename}")
        with open(out_path, "wb") as f:
            f.write(data)

        fake_cid = f"local-{ts}-{file.filename}"
        logger.info("Uploaded %s -> local CID %s", file.filename, fake_cid)
        return {
            "ok": False,             # ❌ IPFS failed, but fallback succeeded
            "cid": fake_cid,         # ✅ still give user a CID
            "bytes": len(data),
            "path": out_path,
            "visibility": visibility,
            "ipfs": False,
        }

    except Exception as e:
        fake_cid = f"failed-{int(time.time())}-{file.filename}"
        logger.error("Upload failed for %s: %s", file.filename, e)
        return {
            "ok": False,
            "cid": fake_cid,   # ✅ even on total failure, a cid-like tag is returned
            "error": str(e),
        }
