"""Configuration loader with YAML parsing, env var substitution, and .env support."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv


def _find_project_root() -> Path:
    """Walk up from this file to find the project root (directory containing config/)."""
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / "config").is_dir():
            return parent
    # Fallback: assume root is three levels up from src/utils/config.py
    return Path(__file__).resolve().parent.parent.parent


def _substitute_env_vars(value: Any) -> Any:
    """Recursively replace ``${VAR}`` placeholders with environment variable values.

    Args:
        value: A string, dict, list, or other YAML-parsed value.

    Returns:
        The same structure with all ``${…}`` references resolved.
    """
    if isinstance(value, str):
        pattern = re.compile(r"\$\{([^}]+)\}")
        def _replacer(match: re.Match) -> str:
            env_key = match.group(1)
            return os.environ.get(env_key, match.group(0))
        return pattern.sub(_replacer, value)
    if isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]
    return value


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load a YAML file and return its contents as a dict.

    Args:
        path: Absolute or relative path to the YAML file.

    Returns:
        Parsed dict, or an empty dict if the file doesn't exist or is empty.
    """
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else {}


class Settings:
    """Singleton that loads ``settings.yaml`` and ``platforms.yaml`` once.

    Values containing ``${ENV_VAR}`` are resolved against the current
    environment (including any variables loaded from ``.env``).
    """

    _instance: Optional["Settings"] = None

    def __init__(self) -> None:
        self._root: Path = _find_project_root()

        # Load .env for local development
        dotenv_path = self._root / ".env"
        if dotenv_path.is_file():
            load_dotenv(dotenv_path)

        self._settings: Dict[str, Any] = _substitute_env_vars(
            _load_yaml(self._root / "config" / "settings.yaml")
        )
        self._platforms: Dict[str, Any] = _substitute_env_vars(
            _load_yaml(self._root / "config" / "platforms.yaml")
        )

    def __getitem__(self, key: str) -> Any:
        """Allow dict-style access to settings values.

        Args:
            key: Top-level settings key.

        Returns:
            The corresponding value from ``settings.yaml``.
        """
        return self._settings[key]

    def get(self, key: str, default: Any = None) -> Any:
        """Safely retrieve a settings value with an optional default.

        Args:
            key: Top-level settings key.
            default: Value returned when *key* is absent.

        Returns:
            The setting value, or *default*.
        """
        return self._settings.get(key, default)

    @property
    def settings(self) -> Dict[str, Any]:
        """Return the full settings dictionary."""
        return self._settings

    @property
    def platforms(self) -> Dict[str, Any]:
        """Return the full platforms dictionary."""
        return self._platforms

    def get_platform(self, platform_name: str) -> Dict[str, Any]:
        """Return configuration for a single platform.

        Args:
            platform_name: Key inside ``platforms.yaml`` (e.g. ``"zhihu"``).

        Returns:
            Platform-specific dict, or an empty dict if not found.
        """
        return self._platforms.get(platform_name, {})

    @classmethod
    def instance(cls) -> "Settings":
        """Return (and lazily create) the singleton ``Settings`` object.

        Returns:
            The shared ``Settings`` instance.
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Discard the cached singleton so the next call reloads configs.

        Useful in tests or after environment changes at runtime.
        """
        cls._instance = None


def get_settings() -> Settings:
    """Return the global ``Settings`` singleton.

    Returns:
        The shared ``Settings`` instance with all config values loaded.
    """
    return Settings.instance()


def get_platform_config(platform_name: str) -> Dict[str, Any]:
    """Convenience helper that returns config for a specific platform.

    Args:
        platform_name: Key inside ``platforms.yaml`` (e.g. ``"zhihu"``).

    Returns:
        Platform-specific dict, or an empty dict if not found.
    """
    return get_settings().get_platform(platform_name)
