"""消息格式化模块"""

from __future__ import annotations

from typing import Any


class MessageFormatter:
    """消息格式化器"""

    @staticmethod
    def format_server_status(status: dict[str, Any]) -> str:
        """格式化服务器状态信息"""
        if "error" in status:
            return f"❌ 获取状态失败: {status['error']}"

        lines = ["📊 Minecraft 服务器状态", f"🟢 在线: {status.get('online', False)}"]

        if status.get("online"):
            lines.extend(
                [
                    f"📦 版本: {status.get('minecraft_version', 'Unknown')}",
                    f"👥 玩家: {status.get('online_players', 0)}/{status.get('max_players', 0)}",
                ]
            )

            if tps := status.get("tps"):
                lines.append(f"⚡ TPS: {tps[0]:.1f} / {tps[1]:.1f} / {tps[2]:.1f}")

            if mem := status.get("memory"):
                lines.append(
                    f"💾 内存: {mem.get('used_mb', 0)}MB / {mem.get('max_mb', 0)}MB ({mem.get('usage_percent', 0):.1f}%)"
                )

            if players := status.get("players"):
                lines.append(f"👤 在线玩家: {', '.join(players)}")

        return "\n".join(lines)

    @staticmethod
    def format_players_info(players_data: dict[str, Any]) -> str:
        """格式化玩家信息"""
        if "error" in players_data:
            return f"❌ 获取玩家信息失败: {players_data['error']}"

        lines = [
            "👥 玩家列表",
            f"在线: {players_data.get('online', 0)}/{players_data.get('max', 0)}",
        ]

        if not (players := players_data.get("list")):
            lines.append("当前无玩家在线")
        else:
            for p in players:
                lines.append(
                    f"• {p.get('name', 'Unknown')} | "
                    f"❤️{p.get('health', 0):.0f}/{p.get('max_health', 20):.0f} | "
                    f"Lv.{p.get('level', 0)} | {p.get('gamemode', 'UNKNOWN')} | "
                    f"{p.get('world', 'unknown')} | {p.get('ping', 0)}ms"
                )

        return "\n".join(lines)

    @staticmethod
    def format_connection_info(
        ws_connected: bool, ws_authenticated: bool, config, forward_targets_count: int
    ) -> str:
        """格式化连接信息"""
        ws_status = (
            "✅ 已连接并认证"
            if ws_connected and ws_authenticated
            else "⚠️ 已连接但未认证"
            if ws_connected
            else "❌ 未连接"
        )

        return f"""🔌 Minecraft 适配器连接状态

WebSocket:
  地址: {config.websocket_host}:{config.websocket_port}
  状态: {ws_status}
  自动重连: {"开启" if config.auto_reconnect else "关闭"}

REST API:
  地址: {config.rest_api_host}:{config.rest_api_port}

消息转发:
  目标数量: {forward_targets_count}
  转发聊天: {"开启" if config.forward_chat_to_astrbot else "关闭"}
  转发进出: {"开启" if config.forward_join_leave_to_astrbot else "关闭"}"""

    @staticmethod
    def format_help() -> str:
        """格式化帮助信息"""
        return """🎮 Minecraft 适配器帮助

指令列表:
  /mc status - 查看服务器状态
  /mc players - 查看在线玩家
  /mc info - 查看插件连接状态
  /mc say <消息> - 向服务器发送消息
  /mc cmd <指令> - 执行服务器指令（仅管理员）
  /mc reconnect - 重新连接服务器
  /mc help - 显示此帮助"""

    @staticmethod
    def format_mc_chat(player: str, message: str) -> str:
        return f"[MC] <{player}> {message}"

    @staticmethod
    def format_mc_player_join(player: str) -> str:
        return f"[MC] ➕ {player} 加入了游戏"

    @staticmethod
    def format_mc_player_leave(player: str) -> str:
        return f"[MC] ➖ {player} 离开了游戏"
