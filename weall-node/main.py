from fastapi import FastAPI

# Import routers
from api import (
    sync,
    governance,
    poh,
    ledger,
    treasury,
    reputation,
    content,
    messaging,
    disputes,
    pinning,
    verification,   # ✅ make sure this line is here
)

# Create the FastAPI app
app = FastAPI(
    title="WeAll Node API",
    description="Backend node API for WeAll network (governance, PoH, ledger, content, disputes, etc.)",
    version="0.1.0",
)

# Mount routers
app.include_router(sync.router, prefix="/sync", tags=["Sync"])
app.include_router(governance.router, prefix="/governance", tags=["Governance"])
app.include_router(poh.router, prefix="/poh", tags=["Proof of Humanity"])
app.include_router(ledger.router, prefix="/ledger", tags=["Ledger"])
app.include_router(treasury.router, prefix="/treasury", tags=["Treasury"])
app.include_router(reputation.router, prefix="/reputation", tags=["Reputation"])
app.include_router(content.router, prefix="/content", tags=["Content"])
app.include_router(messaging.router, prefix="/messaging", tags=["Messaging"])
app.include_router(disputes.router, prefix="/disputes", tags=["Disputes"])
app.include_router(pinning.router, prefix="/pinning", tags=["Pinning / Storage"])
app.include_router(verification.router, prefix="/verification", tags=["Verification"])  # ✅ new unified API

# Root endpoint
@app.get("/")
def root():
    return {"status": "ok", "message": "WeAll node is running"}
