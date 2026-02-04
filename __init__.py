"""
astrbot_plugin_minecraft_adapter

AstrBot may load plugins by file path with a non-package module name, so this plugin
supports both package imports (e.g. `astrbot_plugin_minecraft_adapter.api`) and flat
imports (e.g. `gateway_registry`) when the plugin directory itself is on `sys.path`.
"""

