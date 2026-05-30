"""Async TCP client speaking the Eversolar protocol to the inverter.

This module has **no Home Assistant dependency** so it can be exercised
standalone (see ``tools/probe.py``). The socket connects to the Waveshare
RS485->Ethernet bridge, which transparently forwards the raw frames to the
inverter over serial.
"""

from __future__ import annotations

import asyncio
import logging

from . import protocol

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10  # seconds
READ_TIMEOUT = 8  # seconds to wait for an expected frame (active mode)
# Passive mode waits for a response the *other* master solicits, so it must
# span that master's polling cycle.
PASSIVE_TIMEOUT = 25  # seconds
_READ_CHUNK = 256


class ZeversolarClient:
    """Maintains a raw TCP socket to the inverter and speaks Eversolar."""

    def __init__(
        self,
        host: str,
        port: int,
        inverter_address: int,
        log_raw_frames: bool = False,
        passive: bool = True,
    ) -> None:
        """Initialise the client (no I/O happens here).

        passive=True (default): never transmit; just listen for the
        QueryNormalInfo responses that another bus master (e.g. the Zeversolar
        monitoring module) already solicits. passive=False: act as the master
        ourselves (register + poll) — only valid when no other master exists.
        """
        self._host = host
        self._port = port
        self._inverter_address = inverter_address
        self._log_raw_frames = log_raw_frames
        self._passive = passive
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._buffer = b""
        self._serial: bytes | None = None
        self._registered = False
        self._last_runtime_raw: bytes | None = None

    @property
    def last_runtime_raw(self) -> bytes | None:
        """Raw DATA payload of the most recent QueryNormalInfo response.

        Useful for calibrating FIELD_MAP against a real inverter frame.
        """
        return self._last_runtime_raw

    @property
    def serial(self) -> str | None:
        """Return the inverter serial number, if discovered."""
        return self._serial.decode(errors="replace").strip() if self._serial else None

    async def _connect(self) -> None:
        if self._writer is not None:
            return
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port), CONNECT_TIMEOUT
        )
        self._buffer = b""
        _LOGGER.debug("Connected to %s:%s", self._host, self._port)

    async def close(self) -> None:
        """Drop the socket and forget any registration."""
        self._registered = False
        writer, self._writer, self._reader = self._writer, None, None
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except OSError as err:  # already broken; nothing to do
                _LOGGER.debug("Error while closing socket: %s", err)

    async def _send(self, frame: bytes) -> None:
        assert self._writer is not None
        if self._log_raw_frames:
            _LOGGER.warning("Zeversolar TX: %s", frame.hex(" "))
        self._writer.write(frame)
        await self._writer.drain()

    async def _read_frame(
        self, cc: int, fc: int, timeout: float = READ_TIMEOUT
    ) -> protocol.Frame:
        """Read from the socket until a frame matching (cc, fc) arrives."""
        assert self._reader is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            frames, self._buffer = protocol.parse_frames(self._buffer)
            for frame in frames:
                if self._log_raw_frames:
                    _LOGGER.warning(
                        "Zeversolar RX: cc=0x%02x fc=0x%02x len=%d data=%s",
                        frame.cc,
                        frame.fc,
                        len(frame.data),
                        frame.data.hex(" "),
                    )
                if frame.cc == cc and frame.fc == fc:
                    return frame
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"No frame cc=0x{cc:02x} fc=0x{fc:02x} within {timeout}s"
                )
            chunk = await asyncio.wait_for(self._reader.read(_READ_CHUNK), remaining)
            if not chunk:
                raise ConnectionError("Connection closed by inverter/bridge")
            self._buffer += chunk

    async def _register(self) -> None:
        """Run the discovery + address-assignment handshake."""
        # 1) Offline query -> inverter replies with its serial number.
        await self._send(
            protocol.build_frame(
                protocol.ADDR_HOST,
                protocol.ADDR_BROADCAST,
                protocol.CC_REGISTER,
                protocol.FC_OFFLINE_QUERY,
            )
        )
        resp = await self._read_frame(
            protocol.CC_REGISTER, protocol.FC_OFFLINE_QUERY | protocol.RESPONSE_BIT
        )
        self._serial = resp.data
        _LOGGER.info("Discovered Zeversolar inverter serial %s", self.serial)

        # 2) Assign an address: payload = serial + one address byte.
        payload = self._serial + bytes((self._inverter_address,))
        await self._send(
            protocol.build_frame(
                protocol.ADDR_HOST,
                protocol.ADDR_BROADCAST,
                protocol.CC_REGISTER,
                protocol.FC_SEND_ADDRESS,
                payload,
            )
        )
        ack = await self._read_frame(
            protocol.CC_REGISTER, protocol.FC_SEND_ADDRESS | protocol.RESPONSE_BIT
        )
        _LOGGER.debug("Registration ack: %s", ack.data.hex(" "))
        self._registered = True

    async def async_update(self) -> dict[str, float | str | None]:
        """Obtain one runtime-data frame and decode it.

        Passive: wait for the next QueryNormalInfo response on the bus.
        Active: register (once) then poll for it ourselves.
        """
        try:
            await self._connect()
            if self._passive:
                resp = await self._read_frame(
                    protocol.CC_READ,
                    protocol.FC_QUERY_NORMAL_INFO | protocol.RESPONSE_BIT,
                    timeout=PASSIVE_TIMEOUT,
                )
            else:
                if not self._registered:
                    await self._register()
                await self._send(
                    protocol.build_frame(
                        protocol.ADDR_HOST,
                        self._inverter_address,
                        protocol.CC_READ,
                        protocol.FC_QUERY_NORMAL_INFO,
                    )
                )
                resp = await self._read_frame(
                    protocol.CC_READ,
                    protocol.FC_QUERY_NORMAL_INFO | protocol.RESPONSE_BIT,
                )
            # In passive mode the response's source address is the inverter.
            if self._passive and self._serial is None:
                self._serial = f"addr-0x{resp.src:04x}".encode()
            self._last_runtime_raw = resp.data
            data: dict[str, float | str | None] = dict(
                protocol.decode_runtime(resp.data)
            )
            data["serial"] = self.serial
            return data
        except (
            OSError,
            asyncio.IncompleteReadError,
            asyncio.TimeoutError,  # distinct from builtin TimeoutError on <3.11
            TimeoutError,
            ConnectionError,
        ):
            # Force a clean reconnect + re-register on the next poll.
            await self.close()
            raise
