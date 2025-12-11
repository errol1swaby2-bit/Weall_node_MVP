"""
weall_node/app.py
-----------------
Thin entrypoint for running the WeAll FastAPI app via:

    uvicorn weall_node.app:app

All real route wiring lives in weall_node.weall_api.
"""

from .weall_api import app as app  # re-export for uvicorn


if __name__ == "__main__":
    # Convenience for: python -m weall_node.app
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
