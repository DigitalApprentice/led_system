"""
WiFi manager for ESP32 MicroPython.
Supports STA (station) and AP (access point) modes with fallback.
"""
import network
import time


def connect(credentials, settings, timeout_ms=15000):
    """
    Initialize WiFi based on settings.
    Returns (wlan, ip_address) or (None, None) on failure.
    """
    ssid = credentials.WIFI_SSID
    password = credentials.WIFI_PASSWORD
    ap_ssid = credentials.WIFI_AP_SSID
    ap_password = credentials.WIFI_AP_PASSWORD

    wlan = network.WLAN(network.STA_IF)
    ap = network.WLAN(network.AP_IF)

    ap.active(False)
    wlan.active(True)

    ap_mode = settings.get("wifi_ap_mode", False)

    if ap_mode:
        wlan.active(False)
        ap.active(True)
        ap.config(essid=ap_ssid, password=ap_password, authmode=network.AUTH_WPA_WPA2_PSK)
        print("[WiFi] AP mode:", ap_ssid)
        return ap, ap.ifconfig()[0]

    # STA mode
    if not ssid or ssid == "YourNetwork":
        print("[WiFi] No SSID configured, starting AP fallback")
        wlan.active(False)
        ap.active(True)
        ap.config(essid=ap_ssid, password=ap_password, authmode=network.AUTH_WPA_WPA2_PSK)
        return ap, ap.ifconfig()[0]

    if settings.get("wifi_static_ip_enabled", False):
        static_ip = settings.get("wifi_static_ip")
        subnet = settings.get("wifi_static_subnet", "255.255.255.0")
        gateway = settings.get("wifi_static_gateway")
        dns = settings.get("wifi_static_dns", gateway)
        if static_ip and gateway:
            try:
                wlan.ifconfig((static_ip, subnet, gateway, dns))
                print("[WiFi] Static IP configured:", static_ip)
            except Exception as e:
                print("[WiFi] Failed to set static IP:", e)

    wlan.connect(ssid, password)
    print("[WiFi] Connecting to", ssid, "...")

    start = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), start) > timeout_ms:
            print("[WiFi] STA timeout, starting AP fallback")
            wlan.active(False)
            ap.active(True)
            ap.config(essid=ap_ssid, password=ap_password, authmode=network.AUTH_WPA_WPA2_PSK)
            return ap, ap.ifconfig()[0]
        time.sleep_ms(200)

    ip = wlan.ifconfig()[0]
    print("[WiFi] Connected, IP:", ip)
    return wlan, ip


def disconnect(wlan):
    """Disconnect and deactivate WiFi."""
    if wlan:
        wlan.active(False)
