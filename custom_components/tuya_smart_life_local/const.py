from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "tuya_smart_life_local"
PLATFORMS = [Platform.SWITCH]

CONF_APP_ID = "app_id"
CONF_APP_SECRET = "app_secret"
CONF_APP_VERSION = "app_version"
CONF_BMP_KEY = "bmp_key"
CONF_CERT_SHA256 = "cert_sha256"
CONF_COUNTRY_CODE = "country_code"
CONF_DEVICE_CORE_VERSION = "device_core_version"
CONF_NATIVE_KEY_TEXT = "native_key_text"
CONF_OS_SYSTEM = "os_system"
CONF_PACKAGE_NAME = "package_name"
CONF_SELECTED_HOME_IDS = "selected_home_ids"
CONF_SDK_VERSION = "sdk_version"

DEFAULT_APP_VERSION = "7.8.6"
DEFAULT_COUNTRY_CODE = "84"
DEFAULT_DEVICE_CORE_VERSION = "5.17.0"
DEFAULT_OS_SYSTEM = "15"
DEFAULT_PACKAGE_NAME = "com.tuya.smart"
DEFAULT_SDK_VERSION = "5.24.0"
DEFAULT_SCAN_INTERVAL_SECONDS = 1800

ENTRY_RUNTIME = "runtime"
