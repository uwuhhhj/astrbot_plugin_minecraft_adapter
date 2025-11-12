"""
AstrBot Minecraft Adapter Plugin
连接 Minecraft 服务器的 AstrBot 插件
"""

from __future__ import annotations

import asyncio

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.platform import AstrBotMessage, MessageType, PlatformMetadata
from astrbot.api.star import Context, Star
from astrbot.core.message.components import Plain
from astrbot.core.platform.astrbot_message import MessageMember

from .config import MinecraftAdapterConfig
from .message_formatter import MessageFormatter
from .rest_api_client import RestApiClient
from .utils import get_sender_display_name, parse_command_args
from .websocket_client import WebSocketClient


class MinecraftMessageEvent(AstrMessageEvent):
    """Minecraft 消息事件，支持发送回复到游戏服务器"""

    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        ws_client: WebSocketClient,
    ):
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.ws_client = ws_client

    async def send(self, message: MessageChain):
        """发送消息到 Minecraft 服务器"""
        # 调用父类方法记录指标
        await super().send(message)

        # 提取纯文本消息
        text_parts = []
        for component in message.chain:
            if isinstance(component, Plain):
                text_parts.append(component.text)

        message_str = "".join(text_parts).strip()
        if not message_str:
            return

        # 发送到 Minecraft 服务器（AI 作为发送者）
        success = await self.ws_client.send_chat(message_str, "AI")
        if success:
            logger.debug(f"[MC适配器] AI 回复已发送: {message_str[:50]}...")
        else:
            logger.warning("[MC适配器] AI 回复发送失败")


class MinecraftAdapter(Star):
    """Minecraft 服务器适配器插件"""

    # 类级别的运行标志，确保只有一个实例在运行
    _instance_running = False
    _instance_lock = asyncio.Lock()

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.context = context
        self.config = MinecraftAdapterConfig.from_dict(config)

        # 初始化组件
        self.ws_client = WebSocketClient(self.config)
        self.rest_client = RestApiClient(self.config)
        self.formatter = MessageFormatter()
        self.status_task: asyncio.Task | None = None

        # MC 群聊会话 ID（固定格式）
        self.mc_group_session_id = "minecraft:group:server"

        # 注册消息处理器
        self._register_ws_handlers()

        # 启动插件
        if not self.config.enabled:
            logger.info("[MC适配器] 插件未启用")
        elif not self.config.websocket_token:
            logger.warning("[MC适配器] 未配置 Token，请设置 websocket_token")
        else:
            asyncio.create_task(self._safe_start())

    async def _safe_start(self):
        """安全启动，防止重复启动"""
        async with MinecraftAdapter._instance_lock:
            if MinecraftAdapter._instance_running:
                logger.warning("[MC适配器] 已有实例在运行，跳过启动")
                return

            MinecraftAdapter._instance_running = True
            logger.info("[MC适配器] 插件已启用，正在连接...")
            self._log_config_info()
            await self._start()

    def _register_ws_handlers(self):
        """注册 WebSocket 消息处理器"""
        self.ws_client.register_handler("chat", self._handle_chat_message)
        self.ws_client.register_handler("ai_chat", self._handle_ai_chat_message)
        self.ws_client.register_handler("player_join", self._handle_player_join)
        self.ws_client.register_handler("player_leave", self._handle_player_leave)
        self.ws_client.register_handler("status_response", self._handle_status_response)

    def _log_config_info(self):
        """输出配置信息"""
        info_parts = []

        if self.config.auto_forward_prefix:
            session_info = (
                f"{len(self.config.auto_forward_sessions)} 个会话"
                if self.config.auto_forward_sessions
                else "所有会话"
            )
            info_parts.append(f"自动转发: 前缀'{self.config.auto_forward_prefix}' | {session_info}")

        if self.config.forward_target_session:
            info_parts.append(f"消息转发目标: {len(self.config.forward_target_session)} 个")

        ai_status = "已启用" if self.config.enable_ai_chat else "已禁用"
        info_parts.append(f"AI 对话功能{ai_status}")

        for info in info_parts:
            logger.info(f"[MC适配器] {info}")

    async def _start(self):
        """启动插件"""
        logger.info(f"[MC适配器] 启动插件实例: {id(self)}")

        # 启动 WebSocket 客户端
        await self.ws_client.start()

        # 启动状态检查任务
        if self.config.status_check_interval > 0:
            self.status_task = asyncio.create_task(self._status_check_loop())

    async def _status_check_loop(self):
        """定时检查服务器状态"""
        while self.ws_client.running:
            await asyncio.sleep(self.config.status_check_interval)
            if self.ws_client.authenticated:
                await self.ws_client.request_status()

    # WebSocket 消息处理器

    async def _handle_chat_message(self, data: dict):
        """处理普通聊天消息 - 转发到目标会话"""
        if not self.config.forward_chat_to_astrbot:
            return

        player = data.get("player", "Unknown")
        message = data.get("message", "")
        formatted_msg = self.formatter.format_mc_chat(player, message)
        await self._forward_to_astrbot(formatted_msg)

    async def _handle_ai_chat_message(self, data: dict):
        """处理 AI 对话消息 - 创建群聊会话让 AI 可以回复"""
        if not self.config.enable_ai_chat:
            logger.debug("[MC适配器] AI 对话功能未启用，忽略 AI 消息")
            return

        player = data.get("player", "Unknown")
        message = data.get("message", "")

        if not message.strip():
            logger.debug("[MC适配器] AI 消息内容为空，忽略")
            return

        # 构造消息对象
        astr_message = AstrBotMessage()
        astr_message.type = MessageType.GROUP_MESSAGE
        astr_message.self_id = "minecraft_server"
        astr_message.session_id = self.mc_group_session_id
        astr_message.sender = MessageMember(
            user_id=f"mc_player_{player}", nickname=player
        )
        astr_message.message_str = message
        astr_message.message = [Plain(text=message)]
        astr_message.raw_message = data

        # 创建平台元数据
        platform_meta = PlatformMetadata(
            name="minecraft",
            description="Minecraft 服务器适配器",
            id="minecraft_adapter",
        )

        # 创建自定义事件（包含 ws_client 以便发送回复）
        event = MinecraftMessageEvent(
            message_str=message,
            message_obj=astr_message,
            platform_meta=platform_meta,
            session_id=self.mc_group_session_id,
            ws_client=self.ws_client,
        )

        # 标记为唤醒事件，以便触发 LLM 处理
        event.is_wake = True
        event.is_at_or_wake_command = True

        # 将事件提交到事件队列
        self.context.get_event_queue().put_nowait(event)
        logger.debug(f"[MC适配器] 创建 AI 对话事件: [{player}] {message}")

    async def _handle_player_join(self, data: dict):
        """处理玩家加入消息"""
        if not self.config.forward_join_leave_to_astrbot:
            return

        player = data.get("player", "Unknown")
        formatted_msg = self.formatter.format_mc_player_join(player)
        await self._forward_to_astrbot(formatted_msg)

    async def _handle_player_leave(self, data: dict):
        """处理玩家离开消息"""
        if not self.config.forward_join_leave_to_astrbot:
            return

        player = data.get("player", "Unknown")
        formatted_msg = self.formatter.format_mc_player_leave(player)
        await self._forward_to_astrbot(formatted_msg)

    async def _handle_status_response(self, data: dict):
        """处理状态响应"""
        # 这里可以存储最新的服务器状态
        pass

    async def _forward_to_astrbot(self, message: str):
        """转发消息到 AstrBot"""
        logger.info(f"[MC适配器] 收到消息: {message}")
        if not self.config.forward_target_session:
            return

        for target in self.config.forward_target_session:
            try:
                await self.context.send_message(target, MessageChain().message(message))
                logger.debug(f"[MC适配器] 已转发到: {target}")
            except Exception as e:
                logger.error(f"[MC适配器] 转发失败 {target}: {e}")

    # 指令处理器

    def _check_enabled(self, event: AstrMessageEvent) -> bool:
        """检查插件是否启用，返回 False 表示未启用"""
        if not self.config.enabled:
            return False
        return True

    @filter.command_group("mc")
    def mc_group(self):
        """Minecraft 服务器管理指令组"""
        pass

    @mc_group.command("status")
    async def mc_status(self, event: AstrMessageEvent):
        """查看服务器状态"""
        if not self._check_enabled(event):
            yield event.plain_result("❌ Minecraft 适配器未启用")
            return

        status = await self.rest_client.get_server_status()
        yield event.plain_result(self.formatter.format_server_status(status))

    @mc_group.command("players")
    async def mc_players(self, event: AstrMessageEvent):
        """查看在线玩家"""
        if not self._check_enabled(event):
            yield event.plain_result("❌ Minecraft 适配器未启用")
            return

        players = await self.rest_client.get_players_info()
        yield event.plain_result(self.formatter.format_players_info(players))

    @mc_group.command("info")
    async def mc_info(self, event: AstrMessageEvent):
        """查看连接状态"""
        if not self._check_enabled(event):
            yield event.plain_result("❌ Minecraft 适配器未启用")
            return

        info_text = self.formatter.format_connection_info(
            ws_connected=self.ws_client.is_connected(),
            ws_authenticated=self.ws_client.authenticated,
            config=self.config,
            forward_targets_count=len(self.config.forward_target_session),
        )
        yield event.plain_result(info_text)

    @mc_group.command("say")
    async def mc_say(self, event: AstrMessageEvent, message: str):
        """向服务器发送消息"""
        if not self._check_enabled(event):
            yield event.plain_result("❌ Minecraft 适配器未启用")
            return

        sender_name = await get_sender_display_name(event)
        success = await self.ws_client.send_chat(message, sender_name)
        yield event.plain_result(
            "✅ 消息已发送" if success else "❌ 发送失败，请检查连接"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @mc_group.command("cmd")
    async def mc_cmd(self, event: AstrMessageEvent):
        """执行服务器指令（仅管理员）"""
        if not self._check_enabled(event):
            yield event.plain_result("❌ Minecraft 适配器未启用")
            return

        command = parse_command_args(event.message_str.strip(), "cmd")
        if not command:
            yield event.plain_result(
                "❌ 用法: <prefix>mc cmd <指令>\n示例: /mc cmd weather clear"
            )
            return

        success = await self.ws_client.send_command(command)
        yield event.plain_result(
            f"✅ 指令已执行: {command}" if success else "❌ 执行失败，请检查连接"
        )

    @mc_group.command("reconnect")
    async def mc_reconnect(self, event: AstrMessageEvent):
        """重新连接服务器"""
        if not self._check_enabled(event):
            yield event.plain_result("❌ Minecraft 适配器未启用")
            return

        yield event.plain_result("🔄 正在重新连接...")
        success = await self.ws_client.reconnect(timeout=10)

        if success:
            yield event.plain_result("✅ 重新连接成功！")
        elif self.ws_client.is_connected():
            yield event.plain_result("⚠️ 连接已建立但认证失败，请检查 Token")
        else:
            yield event.plain_result("❌ 重新连接失败，请检查服务器状态")

    @mc_group.command("help")
    async def mc_help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        yield event.plain_result(self.formatter.format_help())

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def auto_forward_message(self, event: AstrMessageEvent):
        """自动转发消息到 Minecraft"""
        # 提前检查所有条件
        if not (
            self.config.auto_forward_prefix
            and self.config.enabled
            and self.ws_client.is_connected()
            and self.ws_client.authenticated
        ):
            return

        message_str = event.message_str.strip()
        if not message_str.startswith(self.config.auto_forward_prefix):
            return

        # 检查会话白名单
        if self.config.auto_forward_sessions:
            if event.unified_msg_origin not in self.config.auto_forward_sessions:
                return

        # 移除前缀并获取实际消息
        actual_message = message_str[len(self.config.auto_forward_prefix) :].strip()
        if not actual_message:
            return

        # 转发消息
        sender_name = await get_sender_display_name(event)
        try:
            success = await self.ws_client.send_chat(actual_message, sender_name)
            if success:
                logger.debug(f"[MC适配器] 自动转发: [{sender_name}] {actual_message}")
                yield event.plain_result(f"✅ 已转发: [{sender_name}] {actual_message}")
                event.stop_event()
            else:
                yield event.plain_result("❌ 转发失败，请检查服务器连接")
        except Exception as e:
            logger.error(f"[MC适配器] 自动转发失败: {e}")
            yield event.plain_result(f"❌ 转发失败: {e}")

    async def terminate(self):
        """插件停止时调用"""
        logger.info(f"[MC适配器] 正在停止: {id(self)}")

        # 重置运行标志
        async with MinecraftAdapter._instance_lock:
            MinecraftAdapter._instance_running = False

        # 停止状态检查任务
        if self.status_task and not self.status_task.done():
            self.status_task.cancel()
            try:
                await self.status_task
            except asyncio.CancelledError:
                pass

        # 停止客户端
        await self.ws_client.stop()
        await self.rest_client.close()
        logger.info("[MC适配器] 已停止")
