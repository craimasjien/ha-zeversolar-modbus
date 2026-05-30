"""The Zeversolar (Eversolar protocol) integration.

This integration is configured entirely through YAML as a ``sensor`` platform,
so there is no component-level setup here. See ``sensor.py`` for the platform
entry point and ``README.md`` for configuration.
"""

from __future__ import annotations

from .const import DOMAIN  # noqa: F401  (re-exported for convenience)
