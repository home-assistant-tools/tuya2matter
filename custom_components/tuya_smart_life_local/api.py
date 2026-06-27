from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from .models import (
    TuyaDeviceDescription,
    TuyaHome,
    TuyaMobileConfig,
    TuyaSession,
    device_from_raw,
    device_parent_id,
    home_id_from_raw,
)

TOKEN_API = ("smartlife.m.user.username.token.get", "2.0")
LOGIN_API = ("smartlife.m.user.email.password.login", "3.0")
HOME_LIST_API = ("m.life.home.space.list", "1.0")
OWNED_DEVICE_API = ("m.life.my.group.device.list", "2.2")
DEVICE_GROUP_API = ("m.life.my.group.device.group.list", "4.3")
DEVICE_RELATION_API = ("m.life.my.group.device.relation.list", "3.2")
LOCAL_DEVICE_API = ("m.life.app.smart.local.device.list", "1.1")
ENERGY_DEVICE_API = ("m.energy.home.device.list", "3.0")

NO_POST_DATA = object()

SIGN_KEYS = {
    "a",
    "v",
    "lat",
    "lon",
    "lang",
    "deviceId",
    "appVersion",
    "ttid",
    "h5",
    "h5Token",
    "os",
    "clientId",
    "postData",
    "time",
    "requestId",
    "et",
    "n4h5",
    "sid",
    "chKey",
    "sp",
}

FIXED_RSA_SEED = bytes(
    [
        0xAA,
        0xFD,
        0x12,
        0xF6,
        0x59,
        0xCA,
        0xE6,
        0x34,
        0x89,
        0xB4,
        0x79,
        0xE5,
        0x07,
        0x6D,
        0xDE,
        0xC2,
        0xF0,
        0x6C,
        0xB5,
        0x8F,
    ]
)


class TuyaMobileApiError(Exception):
    """Raised when the mobile API returns an error."""


def md5_hex(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.md5(value).hexdigest()


def swap_sign_string(value: str) -> str:
    return value[8:16] + value[0:8] + value[24:32] + value[16:24]


def post_data_md5_hex(post_data: str | None) -> str:
    return swap_sign_string(md5_hex(post_data)) if post_data else ""


def build_sign_input(params: dict[str, Any]) -> str:
    normalized = dict(params)
    if normalized.get("postData"):
        normalized["postData"] = post_data_md5_hex(normalized["postData"])
    parts = []
    for key in sorted(normalized):
        value = normalized.get(key)
        if key in SIGN_KEYS and value not in (None, ""):
            parts.append(f"{key}={value}")
    return "||".join(parts)


def request_sign(sign_input: str, native_key: bytes) -> str:
    return hmac.new(native_key, sign_input.encode(), hashlib.sha256).hexdigest()


def normalize_cert_sha256(value: str) -> str:
    stripped = value.replace(":", "").replace(" ", "").lower()
    if len(stripped) != 64 or any(ch not in "0123456789abcdef" for ch in stripped):
        raise ValueError("certificate SHA-256 must contain 64 hex characters")
    return ":".join(stripped[i : i + 2].upper() for i in range(0, len(stripped), 2))


def derive_native_signing_key(
    package_name: str,
    cert_sha256: str,
    bmp_key: str,
    app_secret: str,
) -> str:
    cert = normalize_cert_sha256(cert_sha256)
    return f"{package_name}_{cert}_{bmp_key}_{app_secret}"


def rsa_pkcs1_v15_encrypt_hex(
    message: str,
    modulus_dec: str,
    exponent_dec: str,
) -> str:
    modulus = int(modulus_dec)
    exponent = int(exponent_dec)
    key_len = (modulus.bit_length() + 7) // 8
    message_bytes = message.encode()
    padding_len = key_len - len(message_bytes) - 3
    if padding_len < 8:
        raise ValueError("message too long for RSA key")

    padding = (FIXED_RSA_SEED * ((padding_len // len(FIXED_RSA_SEED)) + 1))[
        :padding_len
    ]
    encoded = b"\x00\x02" + padding + b"\x00" + message_bytes
    cipher_int = pow(int.from_bytes(encoded, "big"), exponent, modulus)
    return cipher_int.to_bytes(key_len, "big").hex()


def stable_device_id(email: str, app_id: str, package_name: str) -> str:
    material = f"{package_name}|{app_id}|{email}".encode()
    return hashlib.sha256(material).hexdigest()[:44]


class TuyaSmartLifeMobileApi:
    """Tuya Smart Life mobile API client using the reversed native signature."""

    def __init__(self, config: TuyaMobileConfig) -> None:
        self.config = config
        self.device_id = config.device_id or stable_device_id(
            config.email, config.app_id, config.package_name
        )
        self.native_key = self._native_key()

    def _native_key(self) -> bytes:
        if self.config.native_key_text:
            return self.config.native_key_text.encode()
        if not (self.config.app_secret and self.config.cert_sha256 and self.config.bmp_key):
            raise TuyaMobileApiError(
                "Provide native_key_text, or app_secret + cert_sha256 + bmp_key"
            )
        return derive_native_signing_key(
            self.config.package_name,
            self.config.cert_sha256,
            self.config.bmp_key,
            self.config.app_secret,
        ).encode()

    def request(
        self,
        api: str,
        version: str,
        payload: dict[str, Any] | object = NO_POST_DATA,
        sid: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        params: dict[str, Any] = {
            "a": api,
            "v": version,
            "clientId": self.config.app_id,
            "deviceId": self.device_id,
            "appVersion": self.config.app_version,
            "chKey": "3f7060ea",
            "ttid": "international",
            "lang": "vi_VN",
            "os": "Android",
            "et": "0",
            "time": str(int(time.time())),
            "requestId": str(uuid.uuid4()),
            "sdkVersion": self.config.sdk_version,
            "deviceCoreVersion": self.config.device_core_version,
            "osSystem": self.config.os_system,
            "platform": "y",
            "channel": "oem",
            "appRnVersion": "5.84",
            "bizData": "",
            "cp": "",
            "nd": "",
            "timeZoneId": "Asia/Ho_Chi_Minh",
        }
        if sid:
            params["sid"] = sid
        if payload is not NO_POST_DATA:
            params["postData"] = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            )
        if extra:
            params.update(extra)

        params["sign"] = request_sign(build_sign_input(params), self.native_key)
        request = urllib.request.Request(
            self.config.endpoint,
            data=urllib.parse.urlencode(params).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": f"ThingSmart/{self.config.app_version} Android",
                "Accept-Encoding": "identity",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read().decode(errors="replace"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            try:
                return exc.code, json.loads(body)
            except json.JSONDecodeError as err:
                raise TuyaMobileApiError(body) from err

    def login(self) -> TuyaSession:
        _, token_response = self.request(
            *TOKEN_API,
            {
                "countryCode": self.config.country_code,
                "username": self.config.email,
                "isUid": False,
            },
        )
        self._raise_for_response(token_response, "login token")
        token = token_response["result"]

        password_md5 = md5_hex(self.config.password)
        encrypted_password = rsa_pkcs1_v15_encrypt_hex(
            password_md5,
            token["publicKey"],
            token["exponent"],
        )
        _, login_response = self.request(
            *LOGIN_API,
            {
                "countryCode": self.config.country_code,
                "email": self.config.email,
                "passwd": encrypted_password,
                "options": '{"group": 1,"mfaCode": ""}',
                "token": token["token"],
                "ifencrypt": 1,
            },
        )
        self._raise_for_response(login_response, "password login")
        result = login_response["result"]
        domain = result.get("domain") if isinstance(result.get("domain"), dict) else {}
        return TuyaSession(
            sid=result["sid"],
            ecode=result.get("ecode"),
            uid=result.get("uid"),
            region=domain.get("regionCode"),
            raw=result,
        )

    def list_homes(self, session: TuyaSession) -> list[TuyaHome]:
        _, response = self.request(*HOME_LIST_API, sid=session.sid)
        self._raise_for_response(response, "home list")
        homes = response.get("result") or []
        if not isinstance(homes, list):
            return []
        return [
            TuyaHome(id=home_id_from_raw(home), name=str(home.get("name")), raw=home)
            for home in homes
            if isinstance(home, dict)
        ]

    def list_home_devices(
        self,
        session: TuyaSession,
        home: TuyaHome,
    ) -> list[TuyaDeviceDescription]:
        _, response = self.request(*OWNED_DEVICE_API, {"gid": home.id}, sid=session.sid)
        self._raise_for_response(response, f"device list for {home.name}")
        raw_devices = response.get("result") or []
        if not isinstance(raw_devices, list):
            return []

        parent_ids = {
            parent_id
            for device in raw_devices
            if isinstance(device, dict)
            for parent_id in [device_parent_id(device)]
            if parent_id
        }
        return [
            device_from_raw(device, home, parent_ids)
            for device in raw_devices
            if isinstance(device, dict) and device.get("devId")
        ]

    def fetch_devices(
        self,
        selected_home_ids: set[str],
    ) -> tuple[list[TuyaHome], list[TuyaDeviceDescription], TuyaSession]:
        session = self.login()
        homes = self.list_homes(session)
        devices: list[TuyaDeviceDescription] = []
        for home in homes:
            if home.id in selected_home_ids:
                devices.extend(self.list_home_devices(session, home))
        return homes, devices, session

    @staticmethod
    def _raise_for_response(response: dict[str, Any], context: str) -> None:
        if response.get("success"):
            return
        code = response.get("errorCode") or response.get("code") or "unknown_error"
        msg = response.get("errorMsg") or response.get("msg") or response.get("status")
        raise TuyaMobileApiError(f"{context} failed: {code}: {msg}")
