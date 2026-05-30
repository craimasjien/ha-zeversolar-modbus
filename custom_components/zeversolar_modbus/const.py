"""Constants for the Zeversolar (Eversolar protocol) integration."""

from __future__ import annotations

DOMAIN = "zeversolar_modbus"

DEFAULT_NAME = "Zeversolar"
# The Waveshare default raw-socket port is 4196; some setups use 502.
DEFAULT_PORT = 502
DEFAULT_SCAN_INTERVAL = 30  # seconds
# Address we assign to the inverter during registration (1..254).
DEFAULT_INVERTER_ADDRESS = 10

CONF_INVERTER_ADDRESS = "inverter_address"
CONF_LOG_RAW_FRAMES = "log_raw_frames"
CONF_PASSIVE = "passive"

DEFAULT_LOG_RAW_FRAMES = False

# Default to passive (listen-only): most installs keep the Zeversolar
# monitoring module as the bus master, and we just read the traffic it solicits.
DEFAULT_PASSIVE = True

MANUFACTURER = "Zeversolar"
MODEL = "Zeverlution 2000s"
