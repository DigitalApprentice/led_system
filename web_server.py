import socket
import json
import gc
import time

class NonBlockingWebServer:
    def __init__(self, controller, app_state, ae1, ae2, state_callback=None):
        self.c = controller
        self.app = app_state
        self.ae1 = ae1
        self.ae2 = ae2
        self.state_callback = state_callback
        self.server = None
        self.init_socket()
        self.cache_catalog()
        
    def init_socket(self):
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind(('', 80))
            self.server.listen(4)
            self.server.setblocking(False)
            print("[WebServer] Listening on port 80")
        except Exception as e:
            print("[WebServer] Failed to bind to port 80:", e)
            self.server = None

    def poll(self):
        if not self.server:
            now = time.ticks_ms()
            if not hasattr(self, '_last_init_attempt') or time.ticks_diff(now, self._last_init_attempt) > 10000:
                self._last_init_attempt = now
                print("[WebServer] Retrying socket initialization...")
                self.init_socket()
            return

        try:
            client_sock, client_addr = self.server.accept()
        except OSError:
            return  # No connection pending

        try:
            client_sock.settimeout(0.15)
            req = client_sock.recv(1024)
            if not req:
                client_sock.close()
                return
            
            req_str = req.decode('utf-8', 'ignore')
            lines = req_str.split('\r\n')
            if not lines or len(lines) == 0:
                client_sock.close()
                return
            
            method_path = lines[0].split(' ')
            if len(method_path) < 2:
                client_sock.close()
                return
                
            method, path = method_path[0], method_path[1]
            
            if path.startswith("/api/status"):
                self.send_json_status(client_sock)
            elif path.startswith("/api/catalog"):
                self.send_json_catalog(client_sock)
            elif path.startswith("/api/control"):
                self.handle_control(client_sock, path)
            elif path == "/" or path == "/index.html":
                self.serve_static_file(client_sock, "index.html", "text/html")
            elif path == "/manifest.json":
                self.serve_static_file(client_sock, "manifest.json", "application/json")
            elif path == "/sw.js":
                self.serve_static_file(client_sock, "sw.js", "application/javascript")
            elif path == "/icon.svg":
                self.serve_static_file(client_sock, "icon.svg", "image/svg+xml")
            else:
                client_sock.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 9\r\nConnection: close\r\n\r\nNot Found")
        except Exception as e:
            # Suppress normal socket read timeouts from cluttering the console
            is_timeout = False
            if isinstance(e, OSError):
                if e.args and (e.args[0] in (110, 116, "timed out") or "timeout" in str(e).lower()):
                    is_timeout = True
            if not is_timeout:
                print("[WebServer] Error routing request:", e)
        finally:
            try:
                client_sock.close()
            except:
                pass

    def parse_query(self, path):
        query = {}
        if '?' in path:
            parts = path.split('?', 1)
            qs = parts[1]
            pairs = qs.split('&')
            for pair in pairs:
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    v = v.replace('+', ' ')
                    v = v.replace('%20', ' ').replace('%3A', ':').replace('%2F', '/').replace('%2C', ',')
                    query[k] = v
        return query

    def send_json_status(self, client):
        c = self.c
        app = self.app
        temp = c.temperature + c.settings.get("temp_offset", -1.3)
        
        status = {
            "time": {
                "year": c.year, "month": c.month, "day": c.day,
                "hour": c.hour, "minute": c.minutes, "second": c.seconds,
                "weekday": c.weekday
            },
            "sensors": {
                "temp": temp,
                "humidity": c.humidity,
                "pressure": c.pressure,
                "lux": c.lux
            },
            "weather": {
                "temp": getattr(c, "weather_temp", None),
                "feels_like": getattr(c, "weather_feels_like", None),
                "humidity": getattr(c, "weather_humidity", None),
                "pressure": getattr(c, "weather_pressure", None),
                "description": getattr(c, "weather_description", None),
                "wind_speed": getattr(c, "weather_wind_speed", None),
                "wind_dir": getattr(c, "weather_wind_dir", None),
                "sunrise": getattr(c, "weather_sunrise", None),
                "sunset": getattr(c, "weather_sunset", None),
                "last_sync": getattr(c, "last_weather_sync", 0)
            },
            "led1": {
                "mode": app.led1.mode_name(),
                "effect_index": app.led1.effect_index,
                "brightness": app.led1.brightness,
                "edit_mode": app.led1.edit_mode,
                "params": app.led1.params,
                "favorites": list(app.led1.favorites)
            },
            "led2": {
                "mode": app.led2.mode_name(),
                "effect_index": app.led2.effect_index,
                "brightness": app.led2.brightness,
                "edit_mode": app.led2.edit_mode,
                "params": app.led2.params,
                "favorites": list(app.led2.favorites)
            },
            "global": {
                "focus_led": app.focus_led,
                "auto_enabled": app.auto_enabled,
                "auto_interval_ms": app.auto_interval_ms,
                "beat_sync_enabled": app.beat_sync_enabled,
                "time_sub": app.time_sub,
                "settings": c.settings
            }
        }
        
        client.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n")
        client.sendall(json.dumps(status).encode('utf-8'))

    def cache_catalog(self):
        try:
            with open("catalog_cache.json", "w", encoding="utf-8") as f:
                f.write("[")
                for idx, item in enumerate(self.app.catalog):
                    if idx > 0:
                        f.write(",")
                    
                    params_meta = []
                    for p in item["params"]:
                        if len(p) == 3 and p[2] == "color":
                            params_meta.append({
                                "name": p[0],
                                "default": p[1],
                                "type": "color"
                            })
                        else:
                            params_meta.append({
                                "name": p[0],
                                "default": p[1],
                                "step": p[2],
                                "min": p[3],
                                "max": p[4]
                            })
                    item_dict = {
                        "index": idx,
                        "name": item["name"],
                        "category": item["category"],
                        "mode": item["mode"],
                        "params": params_meta
                    }
                    f.write(json.dumps(item_dict))
                f.write("]")
            print("[WebServer] Pre-rendered catalog cache saved.")
        except Exception as e:
            print("[WebServer] Failed to create catalog cache:", e)

    def send_json_catalog(self, client):
        client.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n")
        try:
            with open("catalog_cache.json", "rb") as f:
                while True:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    client.sendall(chunk)
        except Exception as e:
            print("[WebServer] Error sending cached catalog:", e)
            client.sendall(b"[]")

    def handle_control(self, client, path):
        params = self.parse_query(path)
        led = int(params.get("led", 2))
        menu = self.app.led1 if led == 1 else self.app.led2
        
        action_result = None
        action_name = "WEB_ACTION"
        
        if "effect_index" in params:
            idx = int(params["effect_index"])
            menu.brightness_per_effect[menu.effect_index] = menu.brightness
            menu.effect_index = idx % len(menu.catalog)
            menu.load_params()
            
            # Load stored favorite parameters if selecting a favorite!
            fav_params = menu.favorites.get(menu.effect_index)
            if fav_params:
                menu.params.update(fav_params)
                
            menu.brightness = menu.brightness_per_effect.get(menu.effect_index, 255)
            action_result = "effect"
            action_name = "WEB_SELECT_EFFECT"
            
        if "mode" in params:
            mode_name = params["mode"]
            menu.set_mode(mode_name)
            if menu == self.app.led1 and mode_name == "TIME":
                clock_idx = getattr(self.app, "clock_idx", 0)
                menu.brightness_per_effect[menu.effect_index] = menu.brightness
                menu.effect_index = clock_idx
                menu.load_params()
                fav_params = menu.favorites.get(menu.effect_index)
                if fav_params:
                    menu.params.update(fav_params)
                menu.brightness = menu.brightness_per_effect.get(clock_idx, 255)
            action_result = "mode"
            action_name = "WEB_SET_MODE"
            
        if "brightness" in params:
            br = int(params["brightness"])
            menu.brightness = max(0, min(255, br))
            action_result = "brightness"
            action_name = "WEB_SET_BRIGHTNESS"
            
        if "param" in params and "val" in params:
            param_name = params["param"]
            val_str = params["val"]
            metadata = None
            for p in menu.current_effect().get("params", ()):
                if p[0] == param_name:
                    metadata = p
                    break
            
            if metadata:
                if len(metadata) == 3 and metadata[2] == "color":
                    if val_str.startswith('[') and val_str.endswith(']'):
                        try:
                            items = val_str[1:-1].split(',')
                            val = [int(x.strip()) for x in items]
                        except:
                            val = val_str
                    else:
                        val = val_str
                else:
                    default_val = metadata[1]
                    if isinstance(default_val, bool):
                        val = val_str in ("1", "true", "True")
                    elif isinstance(default_val, float):
                        val = float(val_str)
                    else:
                        try:
                            val = int(val_str)
                        except ValueError:
                            val = val_str
            else:
                if val_str.startswith('[') and val_str.endswith(']'):
                    try:
                        items = val_str[1:-1].split(',')
                        val = [int(x.strip()) for x in items]
                    except:
                        val = val_str
                elif "." in val_str:
                    val = float(val_str)
                elif val_str.lower() in ("true", "false"):
                    val = val_str.lower() == "true"
                else:
                    try:
                        val = int(val_str)
                    except ValueError:
                        val = val_str
            
            if val == "RM":
                import random
                h = random.randint(0, 255)
                from helpers import EffectsHelpers
                r, g, b = EffectsHelpers._hsv_to_rgb(h, 255, 255)
                val = [r, g, b]
            elif val in ("R", "RG"):
                pass

            menu.params[param_name] = val
            if param_name == "color_p":
                if isinstance(val, (list, tuple)):
                    from main import rgb_to_hue
                    menu.params["hue_p"] = rgb_to_hue(val)
                elif isinstance(val, str):
                    menu.params["hue_p"] = -1
            elif param_name == "color_s":
                if isinstance(val, (list, tuple)):
                    from main import rgb_to_hue
                    menu.params["hue_s"] = rgb_to_hue(val)
                elif isinstance(val, str):
                    menu.params["hue_s"] = -1
            elif param_name == "color_t":
                if isinstance(val, (list, tuple)):
                    from main import rgb_to_hue
                    menu.params["hue_t"] = rgb_to_hue(val)
                elif isinstance(val, str):
                    menu.params["hue_t"] = -1
            elif param_name == "color_q":
                if isinstance(val, (list, tuple)):
                    from main import rgb_to_hue
                    menu.params["hue_q"] = rgb_to_hue(val)
                elif isinstance(val, str):
                    menu.params["hue_q"] = -1

            if menu.effect_index in menu.favorites:
                menu.favorites[menu.effect_index] = menu.params.copy()
                if hasattr(menu, "on_change_callback") and menu.on_change_callback:
                    menu.on_change_callback()
            action_result = "param"
            action_name = "WEB_SET_PARAM"
            
        if "auto_enabled" in params:
            self.app.auto_enabled = params["auto_enabled"] in ("1", "true", "True")
            action_result = "auto"
            action_name = "WEB_SET_AUTO"
            
        if "auto_interval" in params:
            self.app.auto_interval_ms = max(3000, min(60000, int(params["auto_interval"])))
            action_result = "auto"
            action_name = "WEB_SET_AUTO_INTERVAL"
            
        if "beat_sync" in params:
            self.app.beat_sync_enabled = params["beat_sync"] in ("1", "true", "True")
            action_result = "beat_sync"
            action_name = "WEB_SET_BEAT_SYNC"
            
        if "action" in params and params["action"] == "RANDOMIZE":
            menu.randomize_params()
            action_result = "param"
            action_name = "WEB_RANDOMIZE_PARAMS"
            
        if "time_sub" in params:
            self.app.time_sub = params["time_sub"]
            action_result = "mode"
            action_name = "WEB_SET_TIME_SUB"
            
        if "focus_led" in params:
            self.app.focus_led = int(params["focus_led"])
            action_result = "focus"
            action_name = "WEB_SET_FOCUS"
            
        if "toggle_favorite" in params:
            menu.toggle_favorite()
            action_result = "favorite"
            action_name = "WEB_TOGGLE_FAVORITE"
            
        if "setting" in params and "val" in params:
            key = params["setting"]
            val_str = params["val"]
            old_val = self.c.settings.get(key)
            
            if key in self.c.settings:
                if isinstance(old_val, bool):
                    val = val_str in ("1", "true", "True")
                elif isinstance(old_val, float):
                    val = float(val_str)
                elif isinstance(old_val, int):
                    val = int(val_str)
                else:
                    val = val_str
            else:
                if val_str.lower() in ("true", "false"):
                    val = val_str.lower() == "true"
                elif "." in val_str:
                    val = float(val_str)
                elif val_str.isdigit():
                    val = int(val_str)
                else:
                    val = val_str
            
            if old_val != val:
                self.c.settings[key] = val
                self.c.save_settings()
                
                if key == "dst_enabled":
                    old_bool = bool(old_val)
                    new_bool = bool(val)
                    if old_bool != new_bool:
                        delta = 3600 if new_bool else -3600
                        self.c.adjust_rtc_time(delta)
                elif key == "timezone_offset":
                    try:
                        old_tz = float(old_val)
                        new_tz = float(val)
                        delta = int((new_tz - old_tz) * 3600)
                        if delta != 0:
                            self.c.adjust_rtc_time(delta)
                    except:
                        pass
                elif key == "buzzer_enabled":
                    self.c.buzzer_active = bool(val)
                
            action_result = "setting"
            action_name = "WEB_SET_SETTING"
            
        if action_result and self.state_callback:
            self.state_callback(action_result, action_name)
            
        client.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"status\":\"ok\"}")

    def serve_static_file(self, client, file_path, content_type):
        try:
            with open(file_path, "rb") as f:
                client.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: " + content_type.encode() + b"\r\nConnection: close\r\n\r\n")
                while True:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    client.sendall(chunk)
        except Exception as e:
            print("[WebServer] Error serving file:", file_path, e)
            client.sendall(b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 21\r\nConnection: close\r\n\r\nInternal Server Error")
