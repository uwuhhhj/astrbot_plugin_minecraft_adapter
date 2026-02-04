from __future__ import annotations

import sys
from pathlib import Path

from astrbot.api.star import Context, Star, register


@register("astrbot_plugin_minecraft_adapter", "Railgun19457", "Minecraft Gateway（WS Server, 443反代）", "2.0.0")
class MinecraftGatewayPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

        # Ensure the plugins root is importable so other plugins can do:
        #   from astrbot_plugin_minecraft_adapter.api import ...
        plugin_dir = Path(__file__).resolve().parent
        plugins_root = plugin_dir.parent
        plugins_root_str = str(plugins_root)
        if plugins_root_str not in sys.path:
            sys.path.insert(0, plugins_root_str)

        # import to trigger @register_platform_adapter
        try:
            from .gateway_platform_adapter import MinecraftGatewayPlatformAdapter  # noqa: F401
        except ImportError:
            from gateway_platform_adapter import MinecraftGatewayPlatformAdapter  # noqa: F401
