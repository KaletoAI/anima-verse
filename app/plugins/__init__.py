"""Plugin system — loads skill packages from the plugins/ directory."""

from .loader import load_all_plugins, discover_packages
from .context import PluginContext
from .base import PluginSkill

__all__ = ['load_all_plugins', 'discover_packages', 'PluginContext', 'PluginSkill']
