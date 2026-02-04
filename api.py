from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from astrbot.api import logger

try:
    from .gateway_registry import get_connection, list_server_ids
except ImportError:
    from gateway_registry import get_connection, list_server_ids


async def send_bind_confirm(
    server_id: str,
    platform: str,
    code: str,
    account_id: str,
    *,
    timeout_sec: float = 10.0,
) -> dict:
    """
    由其它插件调用：向指定 MC 服务器提交绑定确认（platform + code + accountId），并等待返回。
    """
    conn = await get_connection(server_id)
    if conn is None:
        try:
            connected = await list_server_ids()
        except Exception:
            connected = []
        suffix = f" (connected: {', '.join(connected)})" if connected else " (connected: none)"
        raise RuntimeError(f"minecraft server not connected: {server_id}{suffix}")

    request_id = str(uuid4())
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    conn.pending_by_reply_to[request_id] = fut

    payload = {"platform": platform, "code": code, "accountId": account_id}
    msg = {
        "type": "BIND_CONFIRM_REQUEST",
        "id": request_id,
        "timestamp": int(time.time() * 1000),
        "payload": payload,
    }
    await conn.websocket.send_json(msg)

    try:
        resp = await asyncio.wait_for(fut, timeout=timeout_sec)
        logger.info("[MC-GW][BIND] server=%s resp=%s", server_id, resp)
        return resp
    finally:
        conn.pending_by_reply_to.pop(request_id, None)


async def list_connected_server_ids() -> list[str]:
    return await list_server_ids()
