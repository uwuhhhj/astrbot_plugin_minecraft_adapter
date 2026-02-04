# Minecraft Gateway（AstrBot侧WS Server）

本插件把 AstrBot 作为 **WebSocket Server**（建议通过 443 反代对外提供 `wss://`），Minecraft 服务器插件（`AstrBotAdapter`）作为 **WebSocket Client** 主动连接到 AstrBot，从而避免 MC 服务器暴露端口。

## 连接方式

- AstrBot：本地监听 `ws://127.0.0.1:<listen_port><path>`（例如 `ws://127.0.0.1:58008/mc`）
- Nginx/Caddy：将公网 `wss://<domain><path>` 反代到上面的本地端口
- MC：连接 `wss://<domain><path>?serverId=<serverName>&token=<token>`

## 多服

通过 `serverId` 区分多台 MC 服务器。建议 `serverId` 使用每台服务器的 `server.properties`/配置里的服务器名称（或在 MC 插件配置里覆盖）。

## 绑定

MC 侧生成绑定码后会推送 `BIND_CODE_ISSUED`，AstrBot 侧会建模为 **私聊事件**（`FriendMessage`），并在 `event.get_extra("binding")` 中附带结构化数据（含 `server_id/code/player_uuid/...`）。

其它插件可调用：

```python
from astrbot_plugin_minecraft_adapter.api import send_bind_confirm

await send_bind_confirm(server_id="ExampleServer", platform="kook", code="123456", account_id="xxx")
```

