from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Optional
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from astrbot import logger
from astrbot.api.platform import (
    Platform,
    AstrBotMessage,
    MessageMember,
    PlatformMetadata,
    MessageType,
    register_platform_adapter,
)
from astrbot.core.message.components import Plain

try:
    from .gateway_event import MinecraftGatewayEvent
    from .gateway_registry import ServerConnection, get_connection, set_connection
except ImportError:
    from gateway_event import MinecraftGatewayEvent
    from gateway_registry import ServerConnection, get_connection, set_connection


@dataclass
class ServerAuth:
    server_id: str
    token: str


def _now_ms() -> int:
    return int(time.time() * 1000)


def _parse_ws_path(path: str) -> tuple[str, dict[str, list[str]]]:
    parsed = urlparse(path)
    return parsed.path, parse_qs(parsed.query or "")


def _as_list(value: object) -> list:
    # AstrBot 配置可能把 list 配置成单个 string；这里做兼容：
    # - "main" => ["main"]（而不是 ["m","a","i","n"]）
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    return [value]


@register_platform_adapter(
    "minecraft",
    "Minecraft Gateway (WS Server)",
    default_config_tmpl={
        # 在 AstrBot 机器本地监听，交给 443 反代（Nginx/Caddy）对外提供 wss
        "listen_host": "127.0.0.1",
        "listen_port": 58008,
        "path": "/mc",
        # 白名单：serverId（可写单个字符串或列表；与 tokens 按下标配对）
        "server_ids": "ExampleServer",
        # 白名单：token（可写单个字符串或列表；与 server_ids 按下标配对）
        "tokens": "CHANGE_ME",
        # WebSocket ping/pong heartbeat interval (seconds). Useful for keeping
        # reverse proxies (Nginx/Caddy/Cloudflare) from closing idle connections.
        # Set <= 0 to disable ping heartbeats.
        "ws_heartbeat_sec": 5,
    },
)
class MinecraftGatewayPlatformAdapter(Platform):
    def __init__(self, platform_config: dict, platform_settings: dict, event_queue: asyncio.Queue) -> None:
        # 兼容不同 AstrBot 版本的 Platform.__init__ 签名
        init_attempts = [
            (event_queue,),
            (platform_config, event_queue),
            (platform_settings, event_queue),
            (platform_config, platform_settings, event_queue),
        ]
        last_exc: Exception | None = None
        for args in init_attempts:
            try:
                super().__init__(*args)
                last_exc = None
                break
            except TypeError as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc

        self.config = platform_config or {}
        self.settings = platform_settings or {}

        self._server = None
        self._auth: dict[str, str] = {}

        server_ids = _as_list(self.config.get("server_ids"))
        tokens = _as_list(self.config.get("tokens"))

        # 按下标配对
        if len(server_ids) != len(tokens):
            logger.warning(
                "[MC-GW] whitelist config length mismatch: server_ids=%d tokens=%d (will zip shortest)",
                len(server_ids),
                len(tokens),
            )

        for sid_raw, tok_raw in zip(server_ids, tokens):
            sid = str(sid_raw or "").strip()
            tok = str(tok_raw or "").strip()
            if sid and tok:
                self._auth[sid] = tok

        self._listen_host = str(self.config.get("listen_host") or "127.0.0.1")
        self._listen_port = int(self.config.get("listen_port") or 58008)
        self._path = str(self.config.get("path") or "/mc")
        try:
            self._ws_heartbeat_sec = float(self.config.get("ws_heartbeat_sec", 5) or 0)
        except Exception:
            self._ws_heartbeat_sec = 5.0

    def meta(self) -> PlatformMetadata:
        return PlatformMetadata(
            name="minecraft",
            description="Minecraft Gateway (WS Server)",
            id="gateway",
        )

    async def run(self) -> Awaitable[Any]:
        import aiohttp
        from aiohttp import web

        app = web.Application()

        async def ws_handler(request: web.Request):
            # path check
            if request.path != self._path:
                return web.Response(status=404, text="not found")

            qs = request.query
            server_id = (qs.get("serverId") or "").strip()
            token = (qs.get("token") or "").strip()
            if not server_id or not token:
                return web.Response(status=401, text="missing serverId/token")

            expected = self._auth.get(server_id)
            if expected != token:
                return web.Response(status=403, text="invalid token")

            # WS ping/pong heartbeat keeps reverse proxies from closing idle connections.
            # Client also sends application-layer HEARTBEAT/HEARTBEAT_ACK periodically.
            heartbeat = self._ws_heartbeat_sec
            if heartbeat is not None and heartbeat <= 0:
                heartbeat = None
            ws = web.WebSocketResponse(heartbeat=heartbeat)
            await ws.prepare(request)
            ws_id = hex(id(ws))

            # replace existing connection for same serverId
            old = await get_connection(server_id)
            if old is not None:
                try:
                    logger.info(
                        "[MC-GW] replacing existing connection serverId=%s old=%s new=%s",
                        server_id,
                        hex(id(old.websocket)),
                        ws_id,
                    )
                except Exception:
                    pass
                try:
                    await old.websocket.close(code=1000, message=b"replaced")
                except Exception:
                    pass

            conn = ServerConnection(server_id=server_id, websocket=ws, last_seen_ms=_now_ms())
            await set_connection(server_id, conn)
            logger.info("[MC-GW] connected serverId=%s conn=%s", server_id, ws_id)

            # ack
            await ws.send_json(
                {
                    "type": "CONNECTION_ACK",
                    "id": str(uuid4()),
                    "timestamp": _now_ms(),
                    "payload": {"serverId": server_id},
                }
            )

            loop_exc: Exception | None = None
            try:
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            await self._handle_text(conn, msg.data)
                        except Exception as e:
                            loop_exc = e
                            logger.warning(
                                "[MC-GW] ws message handler error serverId=%s conn=%s: %s",
                                server_id,
                                ws_id,
                                e,
                            )
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        loop_exc = ws.exception()
                        break
            except Exception as e:
                loop_exc = e
                logger.warning("[MC-GW] ws loop error serverId=%s conn=%s: %s", server_id, ws_id, e)
            finally:
                close_code = getattr(ws, "close_code", None)
                ws_exc = None
                try:
                    ws_exc = ws.exception()
                except Exception:
                    ws_exc = None
                exc_repr = None
                if loop_exc is not None:
                    exc_repr = repr(loop_exc)
                elif ws_exc is not None:
                    exc_repr = repr(ws_exc)
                # 如果这个连接已被“后来的同 serverId 连接”替换，则不要把新连接从 registry 里清掉
                current = await get_connection(server_id)
                if current is not None and current.websocket is ws:
                    await set_connection(server_id, None)
                    logger.info(
                        "[MC-GW] disconnected serverId=%s conn=%s close_code=%s exc=%s",
                        server_id,
                        ws_id,
                        close_code,
                        exc_repr,
                    )
                else:
                    logger.info(
                        "[MC-GW] disconnected serverId=%s conn=%s close_code=%s exc=%s (replaced)",
                        server_id,
                        ws_id,
                        close_code,
                        exc_repr,
                    )
            return ws

        app.router.add_get(self._path, ws_handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self._listen_host, self._listen_port)
        await site.start()
        self._server = (runner, site)
        logger.info("[MC-GW] listening ws://%s:%s%s", self._listen_host, self._listen_port, self._path)
        self._log_whitelist_startup()

        # block forever
        while True:
            await asyncio.sleep(3600)

    async def send_by_session(self, session, message_chain) -> Awaitable[Any]:
        # 允许插件通过 session 直接发送回 MC（多服路由靠 session_id）。
        await super().send_by_session(session, message_chain)

        session_id = getattr(session, "session_id", None) or ""
        if not session_id:
            return

        # group: session_id = serverId
        # friend(bind): session_id = serverId:playerUuid
        if ":" in session_id:
            server_id, player_uuid = session_id.split(":", 1)
        else:
            server_id, player_uuid = session_id, None

        conn = await get_connection(server_id)
        if conn is None:
            return

        text_parts: list[str] = []
        for comp in message_chain.chain:
            if isinstance(comp, Plain):
                text_parts.append(comp.text)
        text = "".join(text_parts).strip()
        if not text:
            return

        payload = {
            "content": text,
            "source": {"platform": "astrbot", "userName": "AstrBot"},
            "platform": "astrbot",
            "username": "AstrBot",
        }
        msg: dict = {
            "type": "MESSAGE_INCOMING",
            "id": str(uuid4()),
            "timestamp": _now_ms(),
            "payload": payload,
            "target": {"type": "BROADCAST"},
        }
        if player_uuid:
            msg["target"] = {"type": "PLAYER", "playerUuid": player_uuid, "playerName": None}

        await conn.websocket.send_json(msg)

    async def terminate(self):
        if self._server is None:
            return
        runner, _site = self._server
        self._server = None
        try:
            await runner.cleanup()
        except Exception:
            pass

    async def _handle_text(self, conn: ServerConnection, raw: str) -> None:
        conn.last_seen_ms = _now_ms()
        try:
            data = json.loads(raw)
        except Exception:
            logger.warning("[MC-GW] invalid json from %s: %r", conn.server_id, raw[:200])
            return

        msg_type = data.get("type")

        if msg_type == "HEARTBEAT":
            mid = data.get("id") or str(uuid4())
            await conn.websocket.send_json(
                {"type": "HEARTBEAT_ACK", "id": mid, "timestamp": _now_ms(), "payload": {}}
            )
            return

        if msg_type == "BIND_CONFIRM_RESPONSE":
            reply_to = data.get("replyTo")
            payload = data.get("payload") or {}
            if reply_to and reply_to in conn.pending_by_reply_to:
                fut = conn.pending_by_reply_to.pop(reply_to)
                if not fut.done():
                    fut.set_result(payload)
            return

        if msg_type == "MESSAGE_FORWARD":
            try:
                payload = data.get("payload") or {}
                content = (payload.get("content") or "").strip()
                if content:
                    logger.info("[MC-GW] recv MESSAGE_FORWARD serverId=%s content=%s", conn.server_id, content[:200])
            except Exception:
                pass
            await self._commit_chat_event(conn, data)
            return

        if msg_type == "BIND_CODE_ISSUED":
            await self._commit_bind_code_event(conn, data)
            return

        # ignore others for now

    def _log_whitelist_startup(self) -> None:
        server_ids = sorted(self._auth.keys())
        if not server_ids:
            logger.warning("[MC-GW] no serverId/token whitelist loaded (config.server_ids/tokens is empty)")
            return

        logger.info("[MC-GW] whitelist loaded (%d): %s", len(server_ids), ", ".join(server_ids))

        listen_host = self._listen_host
        connect_host = listen_host
        if listen_host in ("0.0.0.0", "::", "[::]"):
            connect_host = "<public-host>"
            logger.info("[MC-GW] listen_host=%s is bind-all; connect using your public IP/domain", listen_host)

        for sid in server_ids:
            tok = self._auth.get(sid, "")
            url = f"ws://{connect_host}:{self._listen_port}{self._path}?serverId={sid}&token={tok}"
            logger.info("[MC-GW] allowed: %s", url)

    async def _commit_chat_event(self, conn: ServerConnection, data: dict) -> None:
        payload = data.get("payload") or {}
        source = data.get("source") or {}
        player = source.get("player") or {}
        content = payload.get("content") or ""
        if not content:
            return

        player_name = player.get("name") or player.get("displayName") or "Unknown"

        abm = AstrBotMessage()
        abm.type = MessageType.GROUP_MESSAGE
        abm.group_id = conn.server_id
        abm.session_id = conn.server_id
        abm.self_id = conn.server_id
        abm.sender = MessageMember(user_id=f"mc:{player_name}", nickname=player_name)
        abm.message_str = content
        abm.message = [Plain(text=content)]
        abm.raw_message = data
        abm.message_id = data.get("id")

        event = MinecraftGatewayEvent(
            message_str=content,
            message_obj=abm,
            platform_meta=self.meta(),
            session_id=conn.server_id,
            server_id=conn.server_id,
        )
        self.commit_event(event)

    async def _commit_bind_code_event(self, conn: ServerConnection, data: dict) -> None:
        payload = data.get("payload") or {}
        code = payload.get("code") or ""
        player_uuid = payload.get("playerUuid") or ""
        player_name = payload.get("playerName") or "Unknown"
        expires_at = payload.get("expiresAt")
        force = bool(payload.get("force", False))
        if not code or not player_uuid:
            return

        # 私聊事件：session_id 带 serverId，避免多服冲突
        session_id = f"{conn.server_id}:{player_uuid}"
        text = f"绑定码 {code}"

        abm = AstrBotMessage()
        abm.type = MessageType.FRIEND_MESSAGE
        abm.group_id = ""
        abm.session_id = session_id
        abm.self_id = conn.server_id
        abm.sender = MessageMember(user_id=player_uuid, nickname=player_name)
        abm.message_str = text
        abm.message = [Plain(text=text)]
        abm.raw_message = data
        abm.message_id = data.get("id")

        # 为了让日志区分不同服：给 event 单独的 PlatformMetadata.id
        platform_meta = PlatformMetadata(name="minecraft", description="Minecraft Gateway (WS Server)", id=conn.server_id)

        event = MinecraftGatewayEvent(
            message_str=text,
            message_obj=abm,
            platform_meta=platform_meta,
            session_id=session_id,
            server_id=conn.server_id,
            player_uuid=player_uuid,
        )
        event.is_wake = True
        event.is_at_or_wake_command = True
        event.set_extra(
            "binding",
            {
                "server_id": conn.server_id,
                "code": code,
                "player_uuid": player_uuid,
                "player_name": player_name,
                "expires_at": expires_at,
                "force": force,
            },
        )
        self.commit_event(event)
