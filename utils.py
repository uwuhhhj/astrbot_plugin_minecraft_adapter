"""辅助工具模块"""

from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent


async def get_sender_display_name(event: AstrMessageEvent) -> str:
    """获取发送者的显示名称（优先群名片）"""
    default_name = event.get_sender_name() or "AstrBot"

    try:
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
            AiocqhttpMessageEvent,
        )

        if not isinstance(event, AiocqhttpMessageEvent):
            return default_name

        group_id = event.get_group_id()
        sender_id = event.get_sender_id()
        bot = getattr(event, "bot", None)

        if not (group_id and sender_id and bot and hasattr(bot, "call_action")):
            return default_name

        member_info = await bot.call_action(
            "get_group_member_info",
            group_id=int(group_id),
            user_id=int(sender_id),
            no_cache=False,
        )
        return member_info.get("card") or member_info.get("nickname") or default_name

    except Exception as e:
        logger.debug(f"[MC适配器] 获取发送者名称失败: {e}")
        return default_name


def parse_command_args(message_str: str, command: str) -> str | None:
    """从消息字符串中解析指令参数"""
    mc_index = message_str.lower().find("mc")
    if mc_index == -1:
        return None

    after_mc = message_str[mc_index + 2 :].strip()
    if not after_mc.lower().startswith(command):
        return None

    return after_mc[len(command) :].strip() or None
