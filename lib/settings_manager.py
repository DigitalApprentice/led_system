"""
Persistent JSON settings manager for LED Controller.
Backs settings to a JSON file on the MicroPython filesystem.
"""
import json
import os

DEFAULTS = {
    "mode": "effects",
    "clock_variant": "time_colon",
    "custom_messages": ["WELCOME", "LED SYSTEM"],
    "effect_catalog_idx": 0,
    "effect_params": {},
    "global_brightness": 63,
    "buzzer_enabled": True,
    "ntp_enabled": False,
    "ntp_server": "pool.ntp.org",
    "timezone_offset": 1,
    "dst_enabled": False,
    "astro_enabled": False,
    "latitude": 52.0,
    "longitude": 21.0,
    "astro_dim_start": -30,
    "astro_dim_end": 30,
    "min_brightness_night": 8,
    "wifi_static_ip_enabled": False,
    "wifi_static_ip": "192.168.101.150",
    "wifi_static_subnet": "255.255.255.0",
    "wifi_static_gateway": "192.168.101.1",
    "wifi_static_dns": "8.8.8.8",
    "favorites_led1": {},
    "favorites_led2": {},
    "status_messages_enabled": True,
}


class SettingsManager:
    def __init__(self, filepath="settings.json"):
        self._filepath = filepath
        self._data = {}
        self.load()

    def load(self):
        """Load settings from JSON file, merging with defaults."""
        self._data = dict(DEFAULTS)
        try:
            if os.stat(self._filepath)[6] > 0:
                with open(self._filepath, "r") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        self._data.update(loaded)
        except (OSError, ValueError, TypeError):
            pass
        return self._data

    def save(self):
        """Persist current settings to JSON file."""
        try:
            with open(self._filepath, "w") as f:
                json.dump(self._data, f)
        except OSError:
            pass

    def get(self, key, default=None):
        """Get a setting value. Falls back to provided default if key missing."""
        return self._data.get(key, default)

    def set(self, key, value, autosave=True):
        """Set a setting value. Optionally save immediately."""
        self._data[key] = value
        if autosave:
            self.save()

    def reset(self, autosave=True):
        """Reset all settings to factory defaults."""
        self._data = dict(DEFAULTS)
        if autosave:
            self.save()

    def all(self):
        """Return a shallow copy of all settings."""
        return dict(self._data)
