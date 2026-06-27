from __future__ import annotations

import asyncio
from dataclasses import fields
import json
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant

from .models import TuyaDeviceDescription

_LOGGER = logging.getLogger(__name__)

DISCOVERY_PORTS = (6666, 6667, 6699, 7000)


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, callback: Callable[[bytes, tuple[str, int]], None]) -> None:
        self._callback = callback

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._callback(data, addr)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("Tuya UDP discovery socket error: %s", exc)


class TuyaLocalRuntime:
    """Local Tuya discovery and command runtime."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.devices: dict[str, TuyaDeviceDescription] = {}
        self.transports: list[asyncio.DatagramTransport] = []
        self._tinytuya_devices: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._scan_task: asyncio.Task[None] | None = None

    async def async_start(self) -> None:
        if self.transports:
            return
        for port in DISCOVERY_PORTS:
            try:
                transport, _ = await self._create_udp_endpoint(port)
            except OSError as err:
                _LOGGER.warning("Unable to listen for Tuya UDP on %s: %s", port, err)
                continue
            self.transports.append(transport)
        self._scan_task = self.hass.loop.create_task(self._scan_loop())

    async def _create_udp_endpoint(
        self,
        port: int,
    ) -> tuple[asyncio.DatagramTransport, asyncio.DatagramProtocol]:
        try:
            return await self.hass.loop.create_datagram_endpoint(
                lambda: _DiscoveryProtocol(self._handle_datagram),
                local_addr=("0.0.0.0", port),
                reuse_port=True,
                allow_broadcast=True,
            )
        except TypeError:
            return await self.hass.loop.create_datagram_endpoint(
                lambda: _DiscoveryProtocol(self._handle_datagram),
                local_addr=("0.0.0.0", port),
                allow_broadcast=True,
            )

    async def async_stop(self) -> None:
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None
        for transport in self.transports:
            transport.close()
        self.transports.clear()
        for device in self._tinytuya_devices.values():
            close = getattr(device, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        self._tinytuya_devices.clear()

    async def _scan_loop(self) -> None:
        while True:
            try:
                await self.async_scan_once()
            except Exception:
                _LOGGER.debug("Tuya UDP scan failed", exc_info=True)
            await asyncio.sleep(60)

    async def async_scan_once(self) -> None:
        await self.hass.async_add_executor_job(self._scan_once)

    def _scan_once(self) -> None:
        try:
            import tinytuya
        except ImportError:
            return
        try:
            results = tinytuya.deviceScan(
                verbose=False,
                maxretry=2,
                color=False,
                poll=False,
                forcescan=True,
            )
        except TypeError:
            results = tinytuya.deviceScan(False, 2)
        except Exception:
            _LOGGER.debug("TinyTuya deviceScan failed", exc_info=True)
            return

        if not isinstance(results, dict):
            return
        for ip, payload in results.items():
            if isinstance(payload, dict):
                self._apply_discovery_payload(payload, str(ip))

    def update_devices(self, devices: list[TuyaDeviceDescription]) -> None:
        existing = self.devices
        next_devices: dict[str, TuyaDeviceDescription] = {}

        # Preserve broadcast-discovered IP/version across cloud metadata refreshes.
        for device in devices:
            old = existing.get(device.dev_id)
            if old:
                if old.ip and old.ip != device.ip:
                    device.ip = old.ip
                if old.protocol_version:
                    device.protocol_version = old.protocol_version
                for field in fields(TuyaDeviceDescription):
                    setattr(old, field.name, getattr(device, field.name))
                next_devices[device.dev_id] = old
            else:
                next_devices[device.dev_id] = device

        self.devices = next_devices
        self._tinytuya_devices.clear()

    def _handle_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            import tinytuya
        except ImportError:
            return

        payload = None
        try:
            payload = tinytuya.decrypt_udp(data)
            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode(errors="replace")
            if isinstance(payload, str):
                payload = json.loads(payload)
        except Exception:
            _LOGGER.debug("Unable to decrypt Tuya UDP broadcast", exc_info=True)
            return

        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    self._apply_discovery_payload(item, addr[0])
            return
        if isinstance(payload, dict):
            self._apply_discovery_payload(payload, addr[0])

    def _apply_discovery_payload(self, payload: dict[str, Any], fallback_ip: str) -> None:
        gw_id = payload.get("gwId") or payload.get("devId") or payload.get("id")
        if not gw_id:
            return
        device = self.devices.get(str(gw_id))
        if not device:
            return

        ip = payload.get("ip") or fallback_ip
        version = payload.get("version") or payload.get("ver")
        changed = False
        if ip and ip != device.ip:
            device.ip = str(ip)
            changed = True
        if version and str(version) != device.protocol_version:
            device.protocol_version = str(version)
            changed = True
        if changed:
            self._tinytuya_devices.pop(device.dev_id, None)
            _LOGGER.debug(
                "Tuya broadcast updated %s ip=%s version=%s",
                device.dev_id,
                device.ip,
                device.protocol_version,
            )

    def boolean_dps(self) -> list[tuple[TuyaDeviceDescription, str, bool]]:
        items: list[tuple[TuyaDeviceDescription, str, bool]] = []
        for device in self.devices.values():
            if not device.local_controllable:
                continue
            for dp_id, value in device.dps.items():
                if isinstance(value, bool):
                    items.append((device, dp_id, value))
        return items

    async def async_status(self, device: TuyaDeviceDescription) -> dict[str, Any]:
        return await self.hass.async_add_executor_job(self._status, device.dev_id)

    async def async_set_dp(
        self,
        device: TuyaDeviceDescription,
        dp_id: str,
        value: bool,
    ) -> Any:
        async with self._lock:
            return await self.hass.async_add_executor_job(
                self._set_dp,
                device.dev_id,
                int(dp_id),
                value,
            )

    def _status(self, dev_id: str) -> dict[str, Any]:
        device = self._tinytuya_device(dev_id)
        if not device:
            raise RuntimeError(f"Device {dev_id} is missing local metadata or IP")
        response = device.status()
        if isinstance(response, dict):
            return response
        return {}

    def _set_dp(self, dev_id: str, dp_id: int, value: bool) -> Any:
        device = self._tinytuya_device(dev_id)
        if not device:
            raise RuntimeError(f"Device {dev_id} is missing local metadata or IP")
        if hasattr(device, "set_value"):
            return device.set_value(dp_id, value)
        return device.set_status(value, switch=dp_id)

    def _tinytuya_device(self, dev_id: str) -> Any:
        existing = self._tinytuya_devices.get(dev_id)
        if existing:
            return existing

        device = self.devices.get(dev_id)
        if not device:
            return None

        try:
            import tinytuya
        except ImportError as err:
            raise RuntimeError("tinytuya is not installed") from err

        if device.is_child:
            parent = self.devices.get(device.parent_dev_id or "")
            if not parent or not parent.ip or not parent.local_key:
                return None
            parent_obj = self._tinytuya_device(parent.dev_id)
            if not parent_obj:
                return None
            tinytuya_device = self._make_tinytuya_device(
                tinytuya,
                device,
                parent.ip,
                parent.local_key,
                parent_obj,
            )
        else:
            if not device.ip or not device.local_key:
                return None
            tinytuya_device = self._make_tinytuya_device(
                tinytuya,
                device,
                device.ip,
                device.local_key,
                None,
            )

        self._tinytuya_devices[dev_id] = tinytuya_device
        return tinytuya_device

    @staticmethod
    def _make_tinytuya_device(
        tinytuya: Any,
        device: TuyaDeviceDescription,
        ip: str,
        local_key: str,
        parent: Any | None,
    ) -> Any:
        version = _protocol_version(device.protocol_version)
        kwargs: dict[str, Any] = {"version": version}
        if parent is not None:
            kwargs["parent"] = parent
            if device.node_id:
                kwargs["cid"] = device.node_id
                kwargs["node_id"] = device.node_id

        try:
            tuya_device = tinytuya.OutletDevice(
                device.dev_id,
                ip,
                local_key,
                **kwargs,
            )
        except TypeError:
            kwargs.pop("node_id", None)
            try:
                tuya_device = tinytuya.OutletDevice(
                    device.dev_id,
                    ip,
                    local_key,
                    **kwargs,
                )
            except TypeError:
                kwargs.pop("cid", None)
                kwargs.pop("parent", None)
                tuya_device = tinytuya.OutletDevice(
                    device.dev_id,
                    ip,
                    local_key,
                    **kwargs,
                )

        if hasattr(tuya_device, "set_version"):
            tuya_device.set_version(version)
        if hasattr(tuya_device, "set_socketPersistent"):
            tuya_device.set_socketPersistent(False)
        if hasattr(tuya_device, "set_socketNODELAY"):
            tuya_device.set_socketNODELAY(True)
        return tuya_device


def _protocol_version(value: str | None) -> float:
    if not value:
        return 3.3
    parts = str(value).strip().split(".")
    try:
        return float(".".join(parts[:2]))
    except ValueError:
        _LOGGER.debug("Unknown Tuya protocol version %s, falling back to 3.3", value)
        return 3.3
