from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import TuyaMobileApiError, TuyaSmartLifeMobileApi
from .const import (
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_APP_VERSION,
    CONF_BMP_KEY,
    CONF_CERT_SHA256,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_CORE_VERSION,
    CONF_NATIVE_KEY_TEXT,
    CONF_OS_SYSTEM,
    CONF_PACKAGE_NAME,
    CONF_SDK_VERSION,
    CONF_SELECTED_HOME_IDS,
    DEFAULT_APP_VERSION,
    DEFAULT_COUNTRY_CODE,
    DEFAULT_DEVICE_CORE_VERSION,
    DEFAULT_OS_SYSTEM,
    DEFAULT_PACKAGE_NAME,
    DEFAULT_SDK_VERSION,
    DOMAIN,
)
from .models import TuyaHome, TuyaMobileConfig

_LOGGER = logging.getLogger(__name__)


def mobile_config_from_data(data: dict[str, Any]) -> TuyaMobileConfig:
    return TuyaMobileConfig(
        email=data[CONF_EMAIL],
        password=data[CONF_PASSWORD],
        country_code=data.get(CONF_COUNTRY_CODE, DEFAULT_COUNTRY_CODE),
        app_id=data[CONF_APP_ID],
        app_secret=data.get(CONF_APP_SECRET) or None,
        cert_sha256=data.get(CONF_CERT_SHA256) or None,
        bmp_key=data.get(CONF_BMP_KEY) or None,
        native_key_text=data.get(CONF_NATIVE_KEY_TEXT) or None,
        package_name=data.get(CONF_PACKAGE_NAME, DEFAULT_PACKAGE_NAME),
        app_version=data.get(CONF_APP_VERSION, DEFAULT_APP_VERSION),
        sdk_version=data.get(CONF_SDK_VERSION, DEFAULT_SDK_VERSION),
        device_core_version=data.get(
            CONF_DEVICE_CORE_VERSION, DEFAULT_DEVICE_CORE_VERSION
        ),
        os_system=data.get(CONF_OS_SYSTEM, DEFAULT_OS_SYSTEM),
    )


def _has_app_material(data: dict[str, Any]) -> bool:
    if data.get(CONF_NATIVE_KEY_TEXT):
        return True
    return bool(
        data.get(CONF_APP_SECRET)
        and data.get(CONF_CERT_SHA256)
        and data.get(CONF_BMP_KEY)
    )


def user_schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
    values = user_input or {}
    return vol.Schema(
        {
            vol.Required(CONF_EMAIL, default=values.get(CONF_EMAIL, "")): str,
            vol.Required(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(
                CONF_COUNTRY_CODE,
                default=values.get(CONF_COUNTRY_CODE, DEFAULT_COUNTRY_CODE),
            ): str,
            vol.Required(CONF_APP_ID, default=values.get(CONF_APP_ID, "")): str,
            vol.Optional(
                CONF_NATIVE_KEY_TEXT, default=values.get(CONF_NATIVE_KEY_TEXT, "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(
                CONF_APP_SECRET, default=values.get(CONF_APP_SECRET, "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(
                CONF_CERT_SHA256, default=values.get(CONF_CERT_SHA256, "")
            ): str,
            vol.Optional(CONF_BMP_KEY, default=values.get(CONF_BMP_KEY, "")): (
                selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                )
            ),
            vol.Optional(
                CONF_PACKAGE_NAME,
                default=values.get(CONF_PACKAGE_NAME, DEFAULT_PACKAGE_NAME),
            ): str,
            vol.Optional(
                CONF_APP_VERSION,
                default=values.get(CONF_APP_VERSION, DEFAULT_APP_VERSION),
            ): str,
            vol.Optional(
                CONF_SDK_VERSION,
                default=values.get(CONF_SDK_VERSION, DEFAULT_SDK_VERSION),
            ): str,
            vol.Optional(
                CONF_DEVICE_CORE_VERSION,
                default=values.get(
                    CONF_DEVICE_CORE_VERSION, DEFAULT_DEVICE_CORE_VERSION
                ),
            ): str,
            vol.Optional(
                CONF_OS_SYSTEM,
                default=values.get(CONF_OS_SYSTEM, DEFAULT_OS_SYSTEM),
            ): str,
        }
    )


def homes_schema(
    homes: list[TuyaHome],
    selected: list[str] | None = None,
) -> vol.Schema:
    default = selected or [home.id for home in homes]
    return vol.Schema(
        {
            vol.Required(CONF_SELECTED_HOME_IDS, default=default): (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": home.id, "label": f"{home.name} ({home.id})"}
                            for home in homes
                        ],
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            )
        }
    )


class TuyaSmartLifeLocalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._user_data: dict[str, Any] = {}
        self._homes: list[TuyaHome] = []

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not _has_app_material(user_input):
                errors["base"] = "missing_app_material"
            else:
                try:
                    config = mobile_config_from_data(user_input)
                    api = TuyaSmartLifeMobileApi(config)
                    session, homes = await self.hass.async_add_executor_job(
                        self._login_and_list_homes, api
                    )
                    await self.async_set_unique_id(
                        f"{user_input[CONF_EMAIL].lower()}:{user_input[CONF_APP_ID]}"
                    )
                    self._abort_if_unique_id_configured()
                    self._user_data = dict(user_input)
                    self._homes = homes
                    _LOGGER.debug(
                        "Authenticated Tuya mobile account uid=%s homes=%s",
                        session.uid,
                        len(homes),
                    )
                    return await self.async_step_select_homes()
                except TuyaMobileApiError as err:
                    _LOGGER.warning("Tuya mobile login failed: %s", err)
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected Tuya mobile login error")
                    errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=user_schema(user_input),
            errors=errors,
        )

    async def async_step_select_homes(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = [str(home_id) for home_id in user_input[CONF_SELECTED_HOME_IDS]]
            if not selected:
                errors["base"] = "no_home_selected"
            else:
                data = dict(self._user_data)
                data[CONF_SELECTED_HOME_IDS] = selected
                return self.async_create_entry(
                    title=f"Tuya Smart Life Local ({self._user_data[CONF_EMAIL]})",
                    data=data,
                )

        return self.async_show_form(
            step_id="select_homes",
            data_schema=homes_schema(self._homes),
            errors=errors,
        )

    @staticmethod
    def _login_and_list_homes(
        api: TuyaSmartLifeMobileApi,
    ) -> tuple[Any, list[TuyaHome]]:
        session = api.login()
        homes = api.list_homes(session)
        if not homes:
            raise TuyaMobileApiError("No homes returned by Tuya mobile API")
        return session, homes

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return TuyaSmartLifeLocalOptionsFlow(config_entry)


class TuyaSmartLifeLocalOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry
        self._homes: list[TuyaHome] = []

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        data = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            selected = [str(home_id) for home_id in user_input[CONF_SELECTED_HOME_IDS]]
            if not selected:
                errors["base"] = "no_home_selected"
            else:
                return self.async_create_entry(
                    title="",
                    data={CONF_SELECTED_HOME_IDS: selected},
                )

        try:
            config = mobile_config_from_data(data)
            api = TuyaSmartLifeMobileApi(config)
            _, homes = await self.hass.async_add_executor_job(
                TuyaSmartLifeLocalConfigFlow._login_and_list_homes,
                api,
            )
            self._homes = homes
        except Exception:
            _LOGGER.exception("Unable to refresh Tuya homes for options flow")
            errors["base"] = "cannot_connect"
            self._homes = [
                TuyaHome(id=str(home_id), name=str(home_id))
                for home_id in data.get(CONF_SELECTED_HOME_IDS, [])
            ]

        selected = list(
            self.config_entry.options.get(
                CONF_SELECTED_HOME_IDS,
                self.config_entry.data.get(CONF_SELECTED_HOME_IDS, []),
            )
        )
        return self.async_show_form(
            step_id="init",
            data_schema=homes_schema(self._homes, selected),
            errors=errors,
        )
