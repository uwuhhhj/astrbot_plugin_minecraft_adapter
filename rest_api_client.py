"""REST API 客户端模块"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aiohttp

from astrbot.api import logger

if TYPE_CHECKING:
    from .config import MinecraftAdapterConfig


class RestApiClient:
    """REST API 客户端"""

    def __init__(self, config: MinecraftAdapterConfig):
        self.config = config

    async def _request(
        self, endpoint: str, method: str = "GET", **kwargs
    ) -> dict[str, Any]:
        """发送 API 请求

        Args:
            endpoint: API 端点
            method: HTTP 方法
            **kwargs: 其他请求参数

        Returns:
            dict: 响应数据
        """
        url = f"{self.config.rest_api_base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.config.rest_api_token}",
            **kwargs.pop("headers", {}),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method, url, headers=headers, **kwargs
                ) as resp:
                    if resp.status == 200:
                        response = await resp.json()
                        # 如果响应包含 data 字段，返回 data
                        if isinstance(response, dict) and "data" in response:
                            return response["data"]
                        return response
                    else:
                        logger.error(
                            f"[MC适配器/REST] API 请求失败: HTTP {resp.status}"
                        )
                        return {"error": f"HTTP {resp.status}"}

        except aiohttp.ClientError as e:
            logger.error(f"[MC适配器/REST] 网络错误: {e}")
            return {"error": f"网络错误: {e}"}
        except Exception as e:
            logger.error(f"[MC适配器/REST] 请求失败: {e}")
            return {"error": str(e)}

    async def get_server_status(self) -> dict[str, Any]:
        """获取服务器状态

        Returns:
            dict: 服务器状态信息
        """
        return await self._request("/api/status")

    async def get_players_info(self) -> dict[str, Any]:
        """获取玩家信息

        Returns:
            dict: 玩家信息
        """
        return await self._request("/api/players")

    async def get_server_info(self) -> dict[str, Any]:
        """获取服务器基本信息

        Returns:
            dict: 服务器基本信息
        """
        return await self._request("/api/info")

    async def get_world_info(self) -> dict[str, Any]:
        """获取世界信息

        Returns:
            dict: 世界信息
        """
        return await self._request("/api/world")
