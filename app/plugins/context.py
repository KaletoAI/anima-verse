"""PluginContext - service API for plugins.

Plugins receive a PluginContext instead of importing from app.* directly.
This keeps the coupling minimal and the plugin API stable.
"""
import os
import logging
import requests as http_lib
from typing import Any, Optional

from app.core.log import get_logger


class PluginContext:
    """Provides the services a plugin may use."""

    def __init__(self, plugin_id: str):
        self.plugin_id = plugin_id
        self.logger: logging.Logger = get_logger(f"plugin.{plugin_id}")
        self.http = http_lib

    def get_config(self, path: str, default: Any = None) -> Any:
        """Read a value from the world config by dotted path
        (e.g. ``skills.<package>.<field>``) — the preferred way for
        packages to read their config_schema-declared settings."""
        try:
            from app.core import config
            return config.get(path, default)
        except Exception:
            return default

    def get_env(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Read an environment variable (legacy env bridge)."""
        return os.environ.get(key, default)

    def get_env_int(self, key: str, default: int = 0) -> int:
        """Read an environment variable as int."""
        return int(os.environ.get(key, str(default)))

    def get_env_bool(self, key: str, default: bool = False) -> bool:
        """Read an environment variable as bool."""
        return os.environ.get(key, str(default)).lower() in ('true', '1', 'yes')
