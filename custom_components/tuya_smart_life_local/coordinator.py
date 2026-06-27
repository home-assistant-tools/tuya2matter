from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TuyaMobileApiError, TuyaSmartLifeMobileApi
from .const import CONF_SELECTED_HOME_IDS, DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN
from .local import TuyaLocalRuntime
from .models import TuyaDeviceDescription, TuyaHome, TuyaMobileConfig, TuyaSession

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TuyaSmartLifeData:
    homes: list[TuyaHome]
    devices: list[TuyaDeviceDescription]
    session: TuyaSession


class TuyaSmartLifeCoordinator(DataUpdateCoordinator[TuyaSmartLifeData]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        runtime: TuyaLocalRuntime,
        config: TuyaMobileConfig,
        selected_home_ids: set[str],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS),
        )
        self.entry = entry
        self.runtime = runtime
        self.config = config
        self.selected_home_ids = selected_home_ids

    async def _async_update_data(self) -> TuyaSmartLifeData:
        try:
            api = TuyaSmartLifeMobileApi(self.config)
            homes, devices, session = await self.hass.async_add_executor_job(
                api.fetch_devices,
                self.selected_home_ids,
            )
        except TuyaMobileApiError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected Tuya update failure: {err}") from err

        self.runtime.update_devices(devices)
        await self.runtime.async_scan_once()
        return TuyaSmartLifeData(homes=homes, devices=devices, session=session)


def selected_home_ids_from_entry(entry: ConfigEntry) -> set[str]:
    selected = entry.options.get(
        CONF_SELECTED_HOME_IDS,
        entry.data.get(CONF_SELECTED_HOME_IDS, []),
    )
    return {str(home_id) for home_id in selected}
