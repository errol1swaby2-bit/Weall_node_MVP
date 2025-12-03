from fastapi import APIRouter
from starlette.responses import RedirectResponse

router = APIRouter()

@router.get("/frontendtendtend/{path:path}", include_in_schema=False)
def _redir_old_frontend(path: str = ""):
    return RedirectResponse(url=f"/frontend/{path}", status_code=307)

@router.get("/frontendtendtend", include_in_schema=False)
def _redir_old_frontend_root():
    return RedirectResponse(url="/frontend/index.html", status_code=307)
