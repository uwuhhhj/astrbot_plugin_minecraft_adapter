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


async def query_bindings(
    server_id: str,
    player_uuid: str,
    *,
    platform: str | None = None,
    timeout_sec: float = 10.0,
) -> dict:
    """
    由其它插件调用：向指定 MC 服务器查询玩家绑定信息，并等待返回。

    返回示例（成功）：
      {"success": True, "message": "ok", "playerUuid": "...", "bindings": [{"platform": "qq", "accountId": "..."}]}
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

    payload: dict = {"playerUuid": player_uuid}
    if platform:
        payload["platform"] = platform

    msg = {
        "type": "BINDING_QUERY_REQUEST",
        "id": request_id,
        "timestamp": int(time.time() * 1000),
        "payload": payload,
    }
    await conn.websocket.send_json(msg)

    try:
        resp = await asyncio.wait_for(fut, timeout=timeout_sec)
        logger.info("[MC-GW][BINDING_QUERY] server=%s resp=%s", server_id, resp)
        return resp
    finally:
        conn.pending_by_reply_to.pop(request_id, None)


async def query_lands(
    server_id: str,
    player_uuid: str,
    *,
    timeout_sec: float = 10.0,
) -> dict:
    """
    Query Lands membership for a player (may belong to multiple lands).
    Response example:
      {"success": True, "message": "ok", "playerUuid": "...", "count": 2, "lands": [{"id": 1, "name": "Foo"}]}
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

    payload: dict = {"playerUuid": player_uuid}
    msg = {
        "type": "LANDS_QUERY_REQUEST",
        "id": request_id,
        "timestamp": int(time.time() * 1000),
        "payload": payload,
    }
    await conn.websocket.send_json(msg)

    try:
        resp = await asyncio.wait_for(fut, timeout=timeout_sec)
        logger.info("[MC-GW][LANDS_QUERY] server=%s resp=%s", server_id, resp)
        return resp
    finally:
        conn.pending_by_reply_to.pop(request_id, None)


async def query_playtime(
    server_id: str,
    player_uuid: str,
    *,
    timeout_sec: float = 10.0,
) -> dict:
    """
    Query playtime (ticks) for a player on the given MC server.
    Response example:
      {"success": True, "message": "ok", "playerUuid": "...", "playtimeTicks": 123}
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

    payload: dict = {"playerUuid": player_uuid}

    msg = {
        "type": "PLAYTIME_QUERY_REQUEST",
        "id": request_id,
        "timestamp": int(time.time() * 1000),
        "payload": payload,
    }
    await conn.websocket.send_json(msg)

    try:
        resp = await asyncio.wait_for(fut, timeout=timeout_sec)
        logger.info("[MC-GW][PLAYTIME_QUERY] server=%s resp=%s", server_id, resp)
        return resp
    finally:
        conn.pending_by_reply_to.pop(request_id, None)


async def query_player_by_external_account(
    server_id: str,
    *,
    platform: str,
    account_id: str,
    timeout_sec: float = 10.0,
) -> dict:
    """
    Query player info by external account (e.g. qq -> playerUuid/playerName/playtimeTicks).

    Response example:
      {"success": True, "message": "ok", "platform": "qq", "accountId": "123",
       "playerUuid": "...", "playerName": "...", "playtimeTicks": 123}
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

    payload = {"platform": platform, "accountId": account_id}
    msg = {
        "type": "EXTERNAL_ACCOUNT_QUERY_REQUEST",
        "id": request_id,
        "timestamp": int(time.time() * 1000),
        "payload": payload,
    }
    await conn.websocket.send_json(msg)

    try:
        resp = await asyncio.wait_for(fut, timeout=timeout_sec)
        logger.info("[MC-GW][EXTERNAL_ACCOUNT_QUERY] server=%s resp=%s", server_id, resp)
        return resp
    finally:
        conn.pending_by_reply_to.pop(request_id, None)
