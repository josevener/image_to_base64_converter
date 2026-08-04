"""Windows Wi-Fi profile and connection inspection service."""

from __future__ import annotations

import locale
import platform
import subprocess
from dataclasses import dataclass


class WifiServiceError(RuntimeError):
    """Raised when Windows Wi-Fi information cannot be read."""


@dataclass(frozen=True)
class WifiProfile:
    name: str
    is_current: bool = False


def _netsh(*arguments: str) -> str:
    if platform.system() != "Windows":
        raise WifiServiceError("Wi-Fi Connections is available on Windows only.")
    result = subprocess.run(
        ["netsh", "wlan", *arguments],
        capture_output=True,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors="replace",
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise WifiServiceError(result.stderr.strip() or "Unable to read Wi-Fi information.")
    return result.stdout


def _pairs(output: str) -> dict[str, str]:
    return {
        key.strip(): value.strip()
        for line in output.splitlines()
        if ":" in line
        for key, value in [line.split(":", 1)]
        if key.strip() and value.strip()
    }


def current_connection() -> dict[str, str]:
    """Return the current wireless interface values reported by Windows."""
    return _pairs(_netsh("show", "interfaces"))


def saved_profiles() -> list[WifiProfile]:
    """Return saved WLAN profiles, marking the current SSID when available."""
    try:
        current_ssid = current_connection().get("SSID", "")
    except WifiServiceError:
        current_ssid = ""
    output = _netsh("show", "profiles")
    names: list[str] = []
    for line in output.splitlines():
        if ":" not in line:
            continue
        label, value = (item.strip() for item in line.split(":", 1))
        if value and "profile" in label.lower() and value not in names:
            names.append(value)
    profiles = [WifiProfile(name, name == current_ssid) for name in names]
    if current_ssid and not any(item.name == current_ssid for item in profiles):
        profiles.insert(0, WifiProfile(current_ssid, True))
    return profiles


def profile_details(name: str, include_password: bool = False) -> dict[str, str]:
    """Return profile details, revealing a saved password only when requested."""
    arguments = ("show", "profile", f"name={name}")
    if include_password:
        arguments = (*arguments, "key=clear")
    details = _pairs(_netsh(*arguments))
    password_keys = [key for key in details if key.lower() in {"key content", "key material"}]
    if include_password:
        password = next((details.pop(key) for key in password_keys), None)
        details["Saved Password"] = password or "Not available for this profile"
    else:
        details["Saved Password"] = "Hidden — select Show Saved Password to reveal"
    return details
