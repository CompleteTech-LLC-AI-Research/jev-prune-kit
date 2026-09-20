"""Load assessment settings from a trusted runtime .env, without dependencies."""
from __future__ import annotations

import os
from pathlib import Path

from .core import PruneError

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
SETTINGS = {"TYPESAFE_API_KEY", "JEV_PRUNE_ALLOW_REMOTE"}


def assessment_environment():
    """Process variables override file values, including explicit empty values."""
    environment = dict(os.environ)
    explicit = environment.get("JEV_PRUNE_ENV_FILE")
    path = Path(explicit).expanduser() if explicit else ENV_FILE
    try:
        with path.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError
        content = raw.decode("utf-8-sig")
    except FileNotFoundError:
        if not explicit:
            return environment
        raise PruneError("Cannot read configured .env file") from None
    except (OSError, ValueError):
        raise PruneError("Cannot read a valid .env file") from None

    values = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        name = name.strip()
        if name not in SETTINGS:
            continue
        value = value.strip()
        if not separator or "\x00" in value:
            raise PruneError("Invalid assessment setting in .env file")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise PruneError("Invalid quoted assessment setting in .env file")
            value = value[1:-1]
        values[name] = value
    return {**values, **environment}
