from __future__ import annotations

import asyncio
import sys
from types import ModuleType
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ServerConnection:
    server_id: str
    websocket: Any
    last_seen_ms: int
    pending_by_reply_to: dict[str, asyncio.Future] = field(default_factory=dict)


_SINGLETON_KEY = "_astrbot_mc_gateway_registry_singleton"
_singleton = sys.modules.get(_SINGLETON_KEY)
if _singleton is None:
    _singleton = ModuleType(_SINGLETON_KEY)
    _singleton._lock = asyncio.Lock()  # type: ignore[attr-defined]
    _singleton._by_server_id = {}  # type: ignore[attr-defined]
    sys.modules[_SINGLETON_KEY] = _singleton

# Always reference state from the singleton so split imports (different module names)
# still share the same connections.
_lock: asyncio.Lock = getattr(_singleton, "_lock")  # type: ignore[assignment]
_by_server_id: dict[str, ServerConnection] = getattr(_singleton, "_by_server_id")  # type: ignore[assignment]


async def set_connection(server_id: str, conn: Optional[ServerConnection]) -> None:
    async with _lock:
        if conn is None:
            _by_server_id.pop(server_id, None)
        else:
            _by_server_id[server_id] = conn


async def get_connection(server_id: str) -> Optional[ServerConnection]:
    async with _lock:
        return _by_server_id.get(server_id)


async def list_server_ids() -> list[str]:
    async with _lock:
        return list(_by_server_id.keys())


# If AstrBot loads plugins by file path, modules may be imported as "flat" files
# (e.g. `gateway_registry`) instead of package modules
# (`astrbot_plugin_minecraft_adapter.gateway_registry`). Since this module holds
# process-wide connection state, we must ensure both names resolve to the same
# module object to avoid split registries.
_this = sys.modules.get(__name__)
if _this is not None:
    if __name__ == "gateway_registry":
        _other_name = "astrbot_plugin_minecraft_adapter.gateway_registry"
    elif __name__ == "astrbot_plugin_minecraft_adapter.gateway_registry":
        _other_name = "gateway_registry"
    else:
        _other_name = ""

    if _other_name:
        _other = sys.modules.get(_other_name)
        if _other is not None and _other is not _this:
            # Both names were imported separately; force them to share the same
            # underlying state objects to avoid split registries.
            try:
                _other_map = getattr(_other, "_by_server_id", None)
                if isinstance(_other_map, dict) and _other_map is not _by_server_id:
                    _by_server_id.update(_other_map)
                setattr(_other, "_lock", _lock)
                setattr(_other, "_by_server_id", _by_server_id)
            except Exception:
                pass

        # Ensure future imports resolve to this module object for both names.
        sys.modules[_other_name] = _this
