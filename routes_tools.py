"""
Public tools listing endpoint.

Routes:
  GET /v1/tools       — list active tools (public, no auth)
  GET /v1/tools/{id}  — single tool details (public)
"""
import logging

from fastapi import APIRouter, HTTPException

from supabase_auth import get_supabase_client

logger = logging.getLogger("routes_tools")

router = APIRouter(prefix="/v1", tags=["tools"])


@router.get("/tools")
async def list_tools():
    """List all active tools."""
    client = get_supabase_client()
    if client is None:
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً")

    try:
        resp = (
            client.table("tools")
            .select("id, display_name, description, version, api_base_path, metadata")
            .eq("is_active", True)
            .order("id")
            .execute()
        )
    except Exception:
        logger.exception("list tools failed")
        raise HTTPException(status_code=503, detail="تعذّر جلب الأدوات")

    return {"tools": resp.data or []}


@router.get("/tools/{tool_id}")
async def get_tool(tool_id: str):
    """Single tool details."""
    client = get_supabase_client()
    if client is None:
        raise HTTPException(status_code=503, detail="الخدمة غير متاحة مؤقتاً")

    try:
        resp = (
            client.table("tools")
            .select("id, display_name, description, version, api_base_path, input_schema, output_schema, metadata")
            .eq("id", tool_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception("get tool failed")
        raise HTTPException(status_code=503, detail="تعذّر جلب الأداة")

    if not resp.data:
        raise HTTPException(status_code=404, detail="الأداة غير موجودة")

    return resp.data[0]
