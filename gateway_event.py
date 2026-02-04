from __future__ import annotations

from typing import Optional

from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.platform import AstrBotMessage, PlatformMetadata
from astrbot.core.message.components import Plain

try:
    from .gateway_registry import get_connection
except ImportError:
    from gateway_registry import get_connection


class MinecraftGatewayEvent(AstrMessageEvent):
    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        *,
        server_id: str,
        player_uuid: Optional[str] = None,
    ):
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.server_id = server_id
        self.player_uuid = player_uuid

    async def send(self, message: MessageChain):
        # 将插件回复发送回 MC。群消息默认广播；私聊默认定向玩家（若提供 player_uuid）。
        text_parts: list[str] = []
        for comp in message.chain:
            if isinstance(comp, Plain):
                text_parts.append(comp.text)
        text = "".join(text_parts).strip()
        if not text:
            await super().send(message)
            return

        conn = await get_connection(self.server_id)
        if conn is None:
            await super().send(message)
            return

        payload = {
            "content": text,
            "source": {"platform": "astrbot", "userName": "AstrBot"},
            "platform": "astrbot",
            "username": "AstrBot",
        }
        msg: dict = {
            "type": "MESSAGE_INCOMING",
            "id": "0",
            "timestamp": 0,
            "payload": payload,
        }

        if self.player_uuid:
            msg["target"] = {"type": "PLAYER", "playerUuid": self.player_uuid, "playerName": None}
        else:
            msg["target"] = {"type": "BROADCAST"}

        await conn.websocket.send_json(msg)
        await super().send(message)
