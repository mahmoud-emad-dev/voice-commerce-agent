from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Response, status

from voice_commerce.config.settings import settings
from voice_commerce.observability.metrics import metrics_content_type, render_metrics

router = APIRouter()


def _allow_metrics_access(x_admin_key: str | None) -> None:
    if settings.app_debug:
        return
    if not settings.metrics_require_admin_key:
        return
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")


@router.get("/metrics")
async def metrics_endpoint(
    response: Response,
    x_admin_key: str | None = Header(default=None),
) -> Response:
    if not settings.metrics_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metrics are disabled")
    _allow_metrics_access(x_admin_key)
    return Response(content=render_metrics(), media_type=metrics_content_type())
