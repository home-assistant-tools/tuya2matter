from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .config_flow import mobile_config_from_data
from .const import DOMAIN, PLATFORMS
from .coordinator import TuyaSmartLifeCoordinator, selected_home_ids_from_entry
from .local import TuyaLocalRuntime


@dataclass(slots=True)
class TuyaSmartLifeRuntime:
    coordinator: TuyaSmartLifeCoordinator
    local: TuyaLocalRuntime


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = {**entry.data, **entry.options}
    config = mobile_config_from_data(data)
    selected_home_ids = selected_home_ids_from_entry(entry)

    local_runtime = TuyaLocalRuntime(hass)
    await local_runtime.async_start()
    coordinator = TuyaSmartLifeCoordinator(
        hass,
        entry,
        local_runtime,
        config,
        selected_home_ids,
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await local_runtime.async_stop()
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = TuyaSmartLifeRuntime(
        coordinator=coordinator,
        local=local_runtime,
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    runtime: TuyaSmartLifeRuntime | None = hass.data.get(DOMAIN, {}).pop(
        entry.entry_id,
        None,
    )
    if runtime:
        await runtime.local.async_stop()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
