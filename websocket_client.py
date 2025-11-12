"""WebSocket 客户端模块"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import TYPE_CHECKING

import websockets

from astrbot.api import logger

if TYPE_CHECKING:
    from .config import MinecraftAdapterConfig


class WebSocketClient:
    """WebSocket 客户端"""

    def __init__(self, config: MinecraftAdapterConfig):
        self.config = config
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.authenticated = False
        self.running = False
        self.ws_task: asyncio.Task | None = None

        # 消息处理回调
        self._message_handlers: dict[str, Callable] = {}

    def register_handler(self, message_type: str, handler: Callable):
        """注册消息处理器

        Args:
            message_type: 消息类型
            handler: 处理函数，接收 data 参数
        """
        self._message_handlers[message_type] = handler

    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self.ws is not None and self.ws.close_code is None

    async def start(self):
        """启动 WebSocket 客户端"""
        if self.running:
            logger.warning("[MC适配器/WS] 客户端已在运行")
            return

        self.running = True
        self.ws_task = asyncio.create_task(self._connect_loop())
        logger.info("[MC适配器/WS] 客户端已启动")

    async def stop(self):
        """停止 WebSocket 客户端"""
        logger.info("[MC适配器/WS] 正在停止客户端...")
        self.running = False

        # 取消连接任务
        if self.ws_task and not self.ws_task.done():
            self.ws_task.cancel()
            try:
                await self.ws_task
            except asyncio.CancelledError:
                pass

        # 关闭连接
        if self.is_connected():
            try:
                await self.ws.close()
            except Exception as e:
                logger.debug(f"[MC适配器/WS] 关闭连接时出错: {e}")

        self.ws = None
        self.authenticated = False
        logger.info("[MC适配器/WS] 客户端已停止")

    async def send_message(self, data: dict) -> bool:
        """发送消息

        Args:
            data: 要发送的数据

        Returns:
            bool: 是否发送成功
        """
        if not self.is_connected():
            logger.warning("[MC适配器/WS] 未连接，无法发送消息")
            return False

        if not self.authenticated:
            logger.warning("[MC适配器/WS] 未认证，无法发送消息")
            return False

        try:
            await self.ws.send(json.dumps(data))
            return True
        except Exception as e:
            logger.error(f"[MC适配器/WS] 发送消息失败: {e}")
            return False

    async def send_chat(self, message: str, sender: str | None = None) -> bool:
        """发送聊天消息

        Args:
            message: 消息内容
            sender: 发送者名称（可选）

        Returns:
            bool: 是否发送成功
        """
        payload = {"type": "chat", "message": message}
        if sender:
            payload["sender"] = sender

        return await self.send_message(payload)

    async def send_command(self, command: str) -> bool:
        """发送指令

        Args:
            command: 指令内容

        Returns:
            bool: 是否发送成功
        """
        return await self.send_message({"type": "command", "command": command})

    async def request_status(self) -> bool:
        """请求服务器状态

        Returns:
            bool: 是否发送成功
        """
        return await self.send_message({"type": "status_request"})

    async def _connect_loop(self):
        """连接循环"""
        while self.running:
            try:
                logger.info(f"[MC适配器/WS] 正在连接到 {self.config.ws_uri}...")

                async with websockets.connect(self.config.ws_uri) as ws:
                    self.ws = ws
                    self.authenticated = False
                    logger.info("[MC适配器/WS] 连接已建立")

                    # 处理消息
                    async for message in ws:
                        await self._handle_message(message)

            except websockets.exceptions.ConnectionClosed:
                logger.warning("[MC适配器/WS] 连接已关闭")
                self.authenticated = False
                self.ws = None

            except Exception as e:
                logger.error(f"[MC适配器/WS] 连接错误: {e}")
                self.authenticated = False
                self.ws = None

            # 自动重连
            if self.running and self.config.auto_reconnect:
                logger.info(
                    f"[MC适配器/WS] {self.config.reconnect_interval} 秒后重新连接..."
                )
                await asyncio.sleep(self.config.reconnect_interval)
            else:
                break

    async def _handle_message(self, message: str):
        """处理接收到的消息

        Args:
            message: 消息字符串
        """
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            # 处理内置协议消息
            if msg_type == "auth_required":
                await self._send_auth()
                return

            elif msg_type == "auth_success":
                self.authenticated = True
                logger.info("[MC适配器/WS] ✅ 认证成功")
                return

            elif msg_type == "auth_failed":
                logger.error("[MC适配器/WS] ❌ 认证失败，请检查 Token")
                self.authenticated = False
                self.running = False
                return

            elif msg_type == "error":
                error_msg = data.get("message", "Unknown error")
                logger.error(f"[MC适配器/WS] 服务器错误: {error_msg}")
                return

            # 协议处理完成后，进行外部事件分发
            if msg_type in self._message_handlers:
                handler = self._message_handlers[msg_type]
                await handler(data)

        except json.JSONDecodeError:
            logger.error(f"[MC适配器/WS] 无法解析消息: {message}")
        except Exception as e:
            logger.error(f"[MC适配器/WS] 处理消息时出错: {e}")

    async def _send_auth(self):
        """发送认证信息"""
        if self.is_connected():
            await self.ws.send(
                json.dumps({"type": "auth", "token": self.config.websocket_token})
            )
            logger.info("[MC适配器/WS] 已发送认证信息")

    async def reconnect(self, timeout: int = 10) -> bool:
        """重新连接

        Args:
            timeout: 超时时间（秒）

        Returns:
            bool: 是否重连成功
        """
        logger.info("[MC适配器/WS] 开始重新连接...")

        # 如果已连接，先断开
        if self.is_connected():
            await self.ws.close()

        # 等待短暂时间让连接完全关闭
        await asyncio.sleep(0.5)

        # 等待重新连接
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            await asyncio.sleep(1)

            # 检查是否已连接并认证
            if self.is_connected() and self.authenticated:
                logger.info("[MC适配器/WS] ✅ 重新连接成功")
                return True

        # 超时未成功
        if self.is_connected() and not self.authenticated:
            logger.warning("[MC适配器/WS] ⚠️ 连接已建立但认证失败")
        else:
            logger.error(f"[MC适配器/WS] ❌ 重新连接失败（{timeout} 秒超时）")

        return False
