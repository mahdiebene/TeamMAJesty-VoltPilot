"""Small same-origin dashboard; expose only an explicit static-file allowlist."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


ROOT = Path(__file__).resolve().parents[1] / "frontend"
ASSETS = {"app.js", "core.mjs", "config.js", "styles.css", "samples.json"}
HEADERS = {
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self' https: http://localhost:* http://127.0.0.1:*; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    ),
}
router = APIRouter()


@router.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(ROOT / "index.html", media_type="text/html", headers=HEADERS)


@router.get("/assets/{name}", include_in_schema=False)
async def asset(name: str):
    if name not in ASSETS:
        raise HTTPException(status_code=404)
    media_type = "text/javascript" if name.endswith((".js", ".mjs")) else (
        "text/css" if name.endswith(".css") else "application/json")
    return FileResponse(ROOT / "assets" / name, media_type=media_type, headers=HEADERS)