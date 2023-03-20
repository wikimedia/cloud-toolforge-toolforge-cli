#!/usr/bin/env python3
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from os.path import expandvars

import yaml

CONFIGS_LESS_TO_MORE_PRIORITY = [
    Path("/etc/toolforge-cli.yaml"),
    Path("~/.toolforge.yaml"),
    Path("~/.config/toolforge.yaml"),
    Path("$XDG_CONFIG_HOME/toolforge.yaml"),
]
LOGGER = logging.getLogger(__name__)


class LoadConfigError(Exception):
    """Raised when unable to load a config file."""


@dataclass(frozen=True)
class BuildConfig:
    dest_repository: str = "tools-harbor.wmcloud.org"
    builder_image: str = "tools-harbor.wmcloud.org/toolforge/heroku-builder-classic:22"
    build_service_namespace: str = "image-build"
    admin_group_names: list[str] = field(default_factory=lambda: ["admins", "system:masters"])

    @classmethod
    def from_dict(cls, dict: dict[str, Any]):
        return cls(**dict)


@dataclass(frozen=True)
class Config:
    build: BuildConfig
    toolforge_prefix: str = "toolforge-"

    @classmethod
    def from_dict(cls, dict: dict[str, Any]):
        return cls(build=BuildConfig.from_dict(dict.get("build", {})))


def load_config() -> Config:
    config_dict: dict[str, Any] = {}
    for file in CONFIGS_LESS_TO_MORE_PRIORITY:
        full_file = Path(expandvars(file.expanduser()))
        if full_file.exists() and full_file.is_file():
            try:
                config_dict.update(yaml.safe_load(full_file.open()))
            except Exception as error:
                # by default the error does not show which file failed to load
                # so we show it here ourselves
                raise LoadConfigError(f"Unable to parse config file {full_file}") from error

            LOGGER.debug("Updating config from %s", full_file)
        else:
            LOGGER.debug("Unable to find config file %s, skipping", full_file)

    try:
        return Config.from_dict(dict=config_dict)
    except Exception as error:
        raise LoadConfigError(f"Unable to load configuration from dict: {config_dict}") from error
