import gc
import random
import time
import micropython

from ir_remote_mapper import IRActionReader
from lib.switches import (
    CMD_UP, CMD_UP_L, CMD_DOWN, CMD_DOWN_L, CMD_LEFT, CMD_LEFT_L,
    CMD_RIGHT, CMD_RIGHT_L, CMD_CONFIRM, CMD_CONFIRM_L, CMD_L1, CMD_L1_L,
    CMD_L2, CMD_L2_L
)

_BUTTON_TO_ACTION = {
    CMD_CONFIRM: "NEXT_PARAM",
    CMD_CONFIRM_L: "TOGGLE_EDIT_MODE",
    CMD_UP: "PARAM_UP",
    CMD_UP_L: "PARAM_UP_LONG",
    CMD_DOWN: "PARAM_DOWN",
    CMD_DOWN_L: "PARAM_DOWN_LONG",
    CMD_LEFT: "PREV_EFFECT",
    CMD_LEFT_L: "PREV_FAVORITE",
    CMD_RIGHT: "NEXT_EFFECT",
    CMD_RIGHT_L: "NEXT_FAVORITE",
    CMD_L1: "LED1_MODE",
    CMD_L1_L: "LED1_POWER",
    CMD_L2: "LED2_MODE",
    CMD_L2_L: "LED2_POWER",
}

# ---- SETTINGS ----
TARGET_FPS             = 25
FRAME_MIN_TIME         = 1000 // TARGET_FPS
OVERLAY_FRAME_MIN_TIME = 50
UI_MESSAGE_MS          = 10000
TOGGLE_COOLDOWN_MS     = 600
AUTO_INTERVAL_MS       = 5000
AUTO_INTERVAL_MIN_MS   = 3000
AUTO_INTERVAL_MAX_MS   = 60000
BRIGHTNESS_STEP        = 16
PARAM_LONG_STEPS       = 3
TEMP_OFFSET            = -1.3
IR_CONFIG_READY = True
IR_MAP_FILE = "/ir_map.conf"

LED1_MODES = ("TIME", "EFFECTS", "OFF")
LED2_MODES = ("TIME", "EFFECTS", "OFF")

_TOGGLE_ACTIONS = ("AUTO_TOGGLE", "LED1_POWER", "LED2_POWER")


def ticks_diff(now, last):
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(now, last)
    return now - last


def effect_category(effect):
    category = effect.get("category")
    if category:
        return category
    name = effect.get("name", "")
    if ("BARS" in name or "SPLIT" in name or "CLASSIC" in name or
            "WATERFALL" in name or "ENERGY" in name or "MATRIX" in name or
            "SPECTRUM" in name):
        return "bars"
    if "GRAVITY" in name or "SPRING" in name or "PENDULUM" in name or "BOUNCE" in name:
        return "gravity"
    if "RAINBOW" in name or "PLASMA" in name or "RADIAL" in name or "PULSE" in name or "GRAD" in name:
        return "color"
    if "STAR" in name or "SPARK" in name or "FIRE" in name or "RAIN" in name:
        return "spark"
    return "other"


class LampMenu:
    def __init__(self, catalog, modes, initial_effect=0, initial_mode=0, on_change_callback=None):
        self.catalog = catalog
        self.modes = modes
        self.effect_index = initial_effect % len(catalog)
        self.param_index = 0
        self.mode_index = initial_mode % len(modes)
        self.last_on_mode_index = self.mode_index
        self.brightness = 255
        self.params = {}
        self.edit_mode = "scenario"
        if hasattr(time, "ticks_ms"):
            self.last_interaction_ms = time.ticks_ms()
        else:
            self.last_interaction_ms = int(time.time() * 1000)
        self.load_params()
        self.brightness_per_effect = {}
        self.favorites = {}
        self.on_change_callback = on_change_callback

    def current_effect(self):
        return self.catalog[self.effect_index]

    def mode_name(self):
        return self.modes[self.mode_index]

    def load_params(self):
        self.params.clear()
        import random
        for meta in self.current_effect().get("params", ()):
            name, val = meta[0], meta[1]
            if val == "RM":
                h = random.randint(0, 255)
                from helpers import EffectsHelpers
                r, g, b = EffectsHelpers._hsv_to_rgb(h, 255, 255)
                val = [r, g, b]
                if name in ("color_p", "color_s", "color_t", "color_q"):
                    hue_key = "hue_" + name[-1]
                    self.params[hue_key] = h
            self.params[name] = val
        self.param_index = 0

        sc = self.current_effect().get("scenario", {})
        speed_val = 1.0
        for k in ("speed", "scroll_speed", "rotation_speed", "fall_speed"):
            if k in sc:
                speed_val = float(sc[k])
                break
        else:
            if "delay" in sc:
                delay = float(sc["delay"])
                speed_val = 1000.0 / delay if delay > 0 else 1.0
        self.params["speed"] = speed_val
        self.edit_mode = "scenario"
        if hasattr(time, "ticks_ms"):
            self.last_interaction_ms = time.ticks_ms()
        else:
            self.last_interaction_ms = int(time.time() * 1000)

    def next_effect(self):
        self.brightness_per_effect[self.effect_index] = self.brightness
        self.effect_index = (self.effect_index + 1) % len(self.catalog)
        self.load_params()
        self.brightness = self.brightness_per_effect.get(self.effect_index, 255)

    def prev_effect(self):
        self.brightness_per_effect[self.effect_index] = self.brightness
        self.effect_index = (self.effect_index - 1) % len(self.catalog)
        self.load_params()
        self.brightness = self.brightness_per_effect.get(self.effect_index, 255)

    def next_param(self):
        params = self.current_effect().get("params", ())
        if not params:
            return False
        self.param_index = (self.param_index + 1) % len(params)
        return True

    def prev_param(self):
        params = self.current_effect().get("params", ())
        if not params:
            return False
        self.param_index = (self.param_index - 1) % len(params)
        return True

    def adjust_param(self, direction):
        params = self.current_effect().get("params", ())
        if not params:
            return False
        meta = params[self.param_index]
        name, default, step, minimum, maximum = meta
        value = self.params.get(name, default) + (step if direction > 0 else -step)
        if value < minimum:
            value = minimum
        elif value > maximum:
            value = maximum
        self.params[name] = value
        if self.effect_index in self.favorites:
            self.favorites[self.effect_index] = self.params.copy()
            if self.on_change_callback:
                self.on_change_callback()
        return True

    def randomize_params(self):
        import random
        changed = False
        for meta in self.current_effect().get("params", ()):
            name = meta[0]
            if len(meta) >= 3 and meta[2] == "color":
                h = random.randint(0, 255)
                from helpers import EffectsHelpers
                r, g, b = EffectsHelpers._hsv_to_rgb(h, 255, 255)
                self.params[name] = [r, g, b]
                if name in ("color_p", "color_s", "color_t", "color_q"):
                    hue_key = "hue_" + name[-1]
                    self.params[hue_key] = h
                changed = True
            else:
                name, _default, _step, minimum, maximum = meta
                if isinstance(minimum, float) or isinstance(maximum, float):
                    self.params[name] = round(random.uniform(minimum, maximum), 2)
                else:
                    self.params[name] = random.randint(int(minimum), int(maximum))
                changed = True
        if changed and self.effect_index in self.favorites:
            self.favorites[self.effect_index] = self.params.copy()
            if self.on_change_callback:
                self.on_change_callback()
        return changed

    def next_mode(self):
        old = self.mode_name()
        self.mode_index = (self.mode_index + 1) % len(self.modes)
        if self.mode_name() != "OFF":
            self.last_on_mode_index = self.mode_index
        elif old != "OFF":
            self.last_on_mode_index = self.modes.index(old)

    def set_mode(self, name):
        if name not in self.modes:
            return False
        self.mode_index = self.modes.index(name)
        if name != "OFF":
            self.last_on_mode_index = self.mode_index
        return True

    def toggle_power(self):
        if self.mode_name() == "OFF":
            self.mode_index = self.last_on_mode_index
        else:
            self.last_on_mode_index = self.mode_index
            self.set_mode("OFF")

    def adjust_brightness(self, direction, step=BRIGHTNESS_STEP):
        self.brightness += step if direction > 0 else -step
        if self.brightness < 0:
            self.brightness = 0
        elif self.brightness > 255:
            self.brightness = 255
        return True

    def adjust_named_param(self, name, direction):
        params = self.current_effect().get("params", ())
        for i in range(len(params)):
            if params[i][0] == name:
                self.param_index = i
                return self.adjust_param(direction)
        return False

    def select_category(self, category):
        count = len(self.catalog)
        start = self.effect_index
        for offset in range(1, count + 1):
            idx = (start + offset) % count
            if effect_category(self.catalog[idx]) == category:
                self.effect_index = idx
                self.load_params()
                return True
        return False

    def get_sibling_scenario_indices(self):
        current_mode = self.current_effect().get("scenario", {}).get("mode", "")
        if not current_mode:
            return [self.effect_index]
        indices = []
        for i, eff in enumerate(self.catalog):
            if eff.get("scenario", {}).get("mode", "") == current_mode:
                indices.append(i)
        return indices

    def adjust_scenario(self, direction):
        siblings = self.get_sibling_scenario_indices()
        if len(siblings) <= 1:
            return False
        try:
            curr_pos = siblings.index(self.effect_index)
        except ValueError:
            return False
        next_pos = (curr_pos + direction) % len(siblings)
        next_effect_index = siblings[next_pos]
        self.brightness_per_effect[self.effect_index] = self.brightness
        self.effect_index = next_effect_index
        self.load_params()
        self.brightness = self.brightness_per_effect.get(self.effect_index, 255)
        return True

    def param_label(self):
        if self.edit_mode == "scenario":
            siblings = self.get_sibling_scenario_indices()
            if len(siblings) > 1:
                try:
                    curr_pos = siblings.index(self.effect_index)
                except ValueError:
                    curr_pos = 0
                return "S:%d/%d" % (curr_pos + 1, len(siblings))
            return "S:SINGLE"
        else:
            params = self.current_effect().get("params", ())
            if not params:
                return "P:NONE"
            name = params[self.param_index][0]
            return "P:%s=%s" % (name, self.params.get(name, ""))

    def toggle_favorite(self):
        if self.effect_index in self.favorites:
            del self.favorites[self.effect_index]
        else:
            self.favorites[self.effect_index] = self.params.copy()
        if self.on_change_callback:
            self.on_change_callback()

    def next_favorite(self):
        favs = sorted(self.favorites)
        if not favs:
            return
        idx = favs.index(self.effect_index) if self.effect_index in favs else -1
        self.brightness_per_effect[self.effect_index] = self.brightness
        self.effect_index = favs[(idx + 1) % len(favs)]
        self.load_params()
        saved = self.favorites.get(self.effect_index)
        if saved:
            self.params.update(saved)
        self.brightness = self.brightness_per_effect.get(self.effect_index, 255)

    def prev_favorite(self):
        favs = sorted(self.favorites)
        if not favs:
            return
        idx = favs.index(self.effect_index) if self.effect_index in favs else 0
        self.brightness_per_effect[self.effect_index] = self.brightness
        self.effect_index = favs[(idx - 1) % len(favs)]
        self.load_params()
        saved = self.favorites.get(self.effect_index)
        if saved:
            self.params.update(saved)
        self.brightness = self.brightness_per_effect.get(self.effect_index, 255)


class AppState:
    def __init__(self, unified_catalog, c):
        self.catalog = unified_catalog
        self.c = c
        clock_idx = 0
        for idx, eff in enumerate(unified_catalog):
            if eff.get("scenario", {}).get("mode", "") == "analog_clock" or "ANALOG" in eff.get("name", ""):
                clock_idx = idx
                break
        self.clock_idx = clock_idx

        horiz_idx = 0
        for idx, eff in enumerate(unified_catalog):
            if "BARS HORIZ" in eff.get("name", ""):
                horiz_idx = idx
                break
        else:
            for idx, eff in enumerate(unified_catalog):
                if eff.get("category") == "bars":
                    horiz_idx = idx
                    break

        self.led1 = LampMenu(unified_catalog, LED1_MODES, initial_effect=clock_idx, initial_mode=0, on_change_callback=self.save_favorites)
        self.led2 = LampMenu(unified_catalog, LED2_MODES, initial_effect=horiz_idx, initial_mode=0, on_change_callback=self.save_favorites)
        
        fav1 = c.settings.get("favorites_led1", {})
        for k, v in fav1.items():
            self.led1.favorites[int(k)] = v
            
        fav2 = c.settings.get("favorites_led2", {})
        for k, v in fav2.items():
            self.led2.favorites[int(k)] = v

        self.focus_led = 2
        self.led1_last_non_clock_idx = horiz_idx
        self.auto_enabled = False
        self.auto_interval_ms = AUTO_INTERVAL_MS
        self.last_auto_ms = 0
        self.ui_message = ""
        self.ui_until = 0
        self.time_sub = "CUSTOM"  # TIME_ONLY, CUSTOM, TIME_CUSTOM
        self._toggle_last_ms = {}
        self.param_hold_start_time = 0
        self.param_hold_direction = 0
        self.auto_category = None
        self.beat_sync_enabled = False
        self.beat_detected = False
        self.s2 = True
        self.status_was_active = False
            
    def save_favorites(self):
        fav1 = {str(k): v for k, v in self.led1.favorites.items()}
        fav2 = {str(k): v for k, v in self.led2.favorites.items()}
        self.c.settings["favorites_led1"] = fav1
        self.c.settings["favorites_led2"] = fav2
        self.c.save_settings()

    def focused(self):
        return self.led1 if self.focus_led == 1 else self.led2

    def focus_next(self):
        self.focus_led = 1 if self.focus_led == 2 else 2

    def handle_action(self, action):
        if not action:
            return None
        if not "CLOCK" in self.led1.current_effect().get("name", ""):
            self.led1_last_non_clock_idx = self.led1.effect_index
        now_ms = time.ticks_ms()
        if action in _TOGGLE_ACTIONS:
            last = self._toggle_last_ms.get(action, 0)
            if ticks_diff(now_ms, last) < TOGGLE_COOLDOWN_MS:
                return None
            self._toggle_last_ms[action] = now_ms
        menu = self.focused()

        if action == "LED1_POWER":
            self.led1.toggle_power()
            self.focus_led = 1
            return "mode"
        if action == "LED2_POWER":
            self.led2.toggle_power()
            self.focus_led = 2
            return "mode"
        if action == "AUTO_TOGGLE":
            self.auto_enabled = not self.auto_enabled
            return "auto"
        if action == "TOGGLE_BEAT_SYNC":
            self.beat_sync_enabled = not self.beat_sync_enabled
            return "beat_sync"
        if action.startswith("AUTO_CATEGORY_"):
            self.auto_category = action[14:].lower()
            return "auto"
        if action == "TOGGLE_FAVORITE":
            menu.toggle_favorite()
            return "favorite"
        if action == "NEXT_FAVORITE":
            menu.next_favorite()
            return "effect"
        if action == "PREV_FAVORITE":
            menu.prev_favorite()
            return "effect"
        if action == "FOCUS_NEXT":
            self.focus_next()
            return "focus"
        if action == "FOCUS_LED1":
            self.focus_led = 1
            return "focus"
        if action == "FOCUS_LED2":
            self.focus_led = 2
            return "focus"
        if action == "NEXT_EFFECT":
            menu.next_effect()
            return "effect"
        if action == "PREV_EFFECT":
            menu.prev_effect()
            return "effect"
        if action == "NEXT_PARAM":
            if menu.edit_mode == "scenario":
                menu.edit_mode = "parameter"
                menu.param_index = 0
                menu.last_interaction_ms = now_ms
                return "param_select"
            else:
                if menu.next_param():
                    menu.last_interaction_ms = now_ms
                    return "param_select"
                else:
                    menu.edit_mode = "scenario"
                    menu.last_interaction_ms = now_ms
                    return "effect"
        if action == "PREV_PARAM":
            if menu.edit_mode == "scenario":
                menu.edit_mode = "parameter"
                params = menu.current_effect().get("params", ())
                menu.param_index = len(params) - 1 if params else 0
                menu.last_interaction_ms = now_ms
                return "param_select"
            else:
                if menu.prev_param():
                    menu.last_interaction_ms = now_ms
                    return "param_select"
                else:
                    menu.edit_mode = "scenario"
                    menu.last_interaction_ms = now_ms
                    return "effect"
        if action in ("TOGGLE_EDIT_MODE", "NEXT_PARAM_LONG"):
            if menu.edit_mode == "scenario":
                menu.edit_mode = "parameter"
                menu.param_index = 0
                menu.last_interaction_ms = now_ms
                return "param_select"
            else:
                menu.edit_mode = "scenario"
                menu.last_interaction_ms = now_ms
                return "effect"
        if action in ("PARAM_UP", "PARAM_UP_LONG"):
            steps = PARAM_LONG_STEPS if action == "PARAM_UP_LONG" else 1
            changed = False
            menu.last_interaction_ms = now_ms
            if menu.edit_mode == "scenario":
                for _ in range(steps):
                    if menu.adjust_scenario(1):
                        changed = True
                return "effect" if changed else None
            else:
                for _ in range(steps):
                    if menu.adjust_param(1):
                        changed = True
                return "param" if changed else None
        if action in ("PARAM_DOWN", "PARAM_DOWN_LONG"):
            steps = PARAM_LONG_STEPS if action == "PARAM_DOWN_LONG" else 1
            changed = False
            menu.last_interaction_ms = now_ms
            if menu.edit_mode == "scenario":
                for _ in range(steps):
                    if menu.adjust_scenario(-1):
                        changed = True
                return "effect" if changed else None
            else:
                for _ in range(steps):
                    if menu.adjust_param(-1):
                        changed = True
                return "param" if changed else None
        if action == "RANDOMIZE":
            return "param" if menu.randomize_params() else None
        if action == "BRIGHTNESS_UP":
            menu.adjust_brightness(1)
            return "brightness"
        if action == "BRIGHTNESS_DOWN":
            menu.adjust_brightness(-1)
            return "brightness"
        if action == "SPEED_UP":
            current_speed = menu.params.get("speed", 1.0)
            menu.params["speed"] = min(20.0, current_speed + 0.2)
            return "speed"
        if action == "SPEED_DOWN":
            current_speed = menu.params.get("speed", 1.0)
            menu.params["speed"] = max(0.1, current_speed - 0.2)
            return "speed"
        if action == "AUTO_INTERVAL_UP":
            self.auto_interval_ms = min(AUTO_INTERVAL_MAX_MS, self.auto_interval_ms + 5000)
            return "auto"
        if action == "AUTO_INTERVAL_DOWN":
            self.auto_interval_ms = max(AUTO_INTERVAL_MIN_MS, self.auto_interval_ms - 5000)
            return "auto"
        if action.startswith("CATEGORY_"):
            category = action[9:].lower()
            return "effect" if menu.select_category(category) else None
        if action == "NEXT_MODE":
            menu.next_mode()
            return "mode"
        if action == "LED2_TIME":
            if self.focus_led == 1:
                current_mode = self.led1.current_effect().get("scenario", {}).get("mode", "")
                if self.led1.mode_name() == "TIME" and current_mode == "analog_clock":
                    self.led1.adjust_scenario(1)
                else:
                    self.led1.set_mode("TIME")
                    for idx, eff in enumerate(self.catalog):
                        if eff.get("scenario", {}).get("mode", "") == "analog_clock":
                            self.led1.brightness_per_effect[self.led1.effect_index] = self.led1.brightness
                            self.led1.effect_index = idx
                            self.led1.load_params()
                            self.led1.brightness = self.led1.brightness_per_effect.get(idx, 255)
                            break
                return "mode"
            else:
                if self.led2.mode_name() == "TIME":
                    subs = ("TIME_ONLY", "CUSTOM", "TIME_CUSTOM")
                    i = subs.index(self.time_sub) if self.time_sub in subs else 2
                    self.time_sub = subs[(i + 1) % 3]
                else:
                    self.led2.set_mode("TIME")
                    self.time_sub = "TIME_ONLY"
                self.focus_led = 2
                return "mode"
        if action == "LED2_TIME_FX":
            self.led2.set_mode("TIME")
            self.time_sub = "TIME_CUSTOM"
            self.focus_led = 2
            return "mode"
        if action == "LED2_FX":
            if self.focus_led == 1:
                current_mode = self.led1.current_effect().get("scenario", {}).get("mode", "")
                if current_mode == "analog_clock":
                    self.led1.brightness_per_effect[self.led1.effect_index] = self.led1.brightness
                    self.led1.effect_index = self.led1_last_non_clock_idx
                    self.led1.load_params()
                    self.led1.brightness = self.led1.brightness_per_effect.get(self.led1_last_non_clock_idx, 255)
                self.led1.set_mode("EFFECTS")
                return "mode"
            else:
                self.led2.set_mode("EFFECTS")
                self.focus_led = 2
                return "mode"
        if action == "LED1_MODE":
            self.led1.next_mode()
            self.focus_led = 1
            return "mode"
        if action == "LED2_MODE":
            self.led2.next_mode()
            self.focus_led = 2
            return "mode"
        return None

    def auto_step(self, now):
        timeout_occurred = False
        for menu in (self.led1, self.led2):
            if menu.edit_mode == "parameter":
                if ticks_diff(now, menu.last_interaction_ms) > 10000:
                    menu.edit_mode = "scenario"
                    menu.last_interaction_ms = now
                    timeout_occurred = True
                    print("[Menu] Parameter edit timeout. Reverted to scenario mode.")
        if timeout_occurred:
            return "param_timeout"

        if not self.auto_enabled:
            return None
        if self.beat_sync_enabled:
            if not self.beat_detected:
                return None
            self.beat_detected = False
        elif ticks_diff(now, self.last_auto_ms) < self.auto_interval_ms:
            return None
        self.last_auto_ms = now
        if self.auto_category:
            menu = self.focused()
            count = len(menu.catalog)
            start = menu.effect_index
            for offset in range(1, count + 1):
                idx = (start + offset) % count
                if effect_category(menu.catalog[idx]) == self.auto_category:
                    menu.brightness_per_effect[menu.effect_index] = menu.brightness
                    menu.effect_index = idx
                    menu.load_params()
                    menu.brightness = menu.brightness_per_effect.get(menu.effect_index, 255)
                    break
        else:
            self.focused().next_effect()
        return "effect"

    def set_ui_message(self, msg, now, duration=1500):
        if not self.c.settings.get("status_messages_enabled", True):
            self.ui_message = ""
            return
        self.ui_message = msg
        self.ui_until = now + duration

    def current_ui_message(self, now):
        if self.ui_message and ticks_diff(self.ui_until, now) > 0:
            return self.ui_message
        return ""


def led2_frame_due(mode_name, now, last_tick):
    if mode_name != "TIME":
        return True
    return ticks_diff(now, last_tick) >= OVERLAY_FRAME_MIN_TIME


def ir_action(reader):
    if reader:
        return reader.read()
    return None


MODE_DEFAULTS = {
    "center_split": {
        "max_height": 36, "center_offset": -7, "show_peaks": True,
        "enable_ghosting": True, "ghosting_factor": 0.7, "enable_peak_flash": True
    },
    "bars": {
        "bar_size": 8, "spacing": 2, "start_row": 20, "reverse_bands": True,
        "show_peaks": False, "enable_ghosting": True, "ghosting_factor": 0.6,
        "enable_symmetric": False, "enable_peak_flash": True, "center_offset": -7
    },
    "classic": {
        "show_peaks": True, "enable_ghosting": True, "ghosting_factor": 0.74,
        "enable_peak_flash": True, "peak_flash_threshold": 180, "gain": 1.0
    },
    "analog_clock": {
        "show_marks": True, "target_brightness": 255, "auto_brightness": True
    },
    "sparkles": {
        "sparkle_count": 4, "enable_ghosting": True, "ghosting_factor": 0.68
    },
    "spiral_audio": {
        "rotation_speed": 4.0, "arms": 4, "enable_ghosting": True, "ghosting_factor": 0.6
    },
    "orbital_dots": {
        "n_dots": 4, "ring": 0, "direction": 1, "speed": 2.0,
        "ghosting": 0.7, "trail": 4, "audio_reactive": True, "pulse": True
    },
    "attractor": {
        "mass": 100, "particles": 82, "size": 1, "friction": 0,
        "color_by_age": False, "move_attractor": False, "swallow": False, "ghosting": 0.7
    },
    "dna": {
        "scroll_speed": 8.0, "cycles": 3, "rung_spacing": 0,
        "enable_ghosting": True, "ghosting_factor": 0.72, "audio_reactive": True
    },
    "fire": {
        "cooling": 175, "sparking": 80, "audio_reactive": False, "speed": 2
    },
    "fireworks": {
        "sparks_per_burst": 14, "gravity": 3, "min_interval": 400, "audio_reactive": True
    },
    "motion_patterns": {
        "speed": 1.0, "direction": 1, "segment_len": 15, "spacing": 15,
        "bg_brightness": 0, "audio_reactive": True, "palette_shift_speed": 0.5
    },
    "plasma_audio": {
        "speed": 3.0, "intensity": 1.5
    },
    "wave_audio": {
        "wave_height": 40, "start_row": 0
    },
    "rain": {
        "start_row": 0, "fall_speed": 1.0
    },
    "fast_bars": {
        "scale": 8
    },
    "fire_ice": {
        "cooling": 175, "sparking": 80, "speed": 2
    },
    "colored_snake": {
        "num_snakes": 3, "min_len": 5, "max_len": 30, "delay": 30
    },
    "static_bars": {
        "rainbow": False, "target_brightness": 255, "auto_brightness": False, "color_interval_ms": 0
    },
    "mixer": {
        "sections": 2, "color_mode": 0, "multiplier_mode": 0, "effect_mode": 1,
        "beginning_offset": 0, "delay_in": 30, "delay_intermediate": 30, "delay_out": 30, "wait_time": 1000, "random_cycle": False,
        "color_p": [255, 255, 255], "color_s": [255, 165, 0], "color_t": [128, 0, 128]
    },
    "rotating": {
        "hue_offset": 0.0
    },
    "spectrum": {
        "hue_offset": 0.0
    },
    "gravity_orbiters": {
        "gravity": 1.3, "friction": 1.2, "n_orbiters": 3
    },
    "gravity_cascade": {
        "gravity": 0.15, "wind": 0.5, "bounce": 0.7
    },
    "planet_orbit": {
        "gravity": 2.0, "speed": 1.0, "planet_count": 3
    },
    "black_hole": {
        "gravity": 2.5, "swallow_radius": 2.0, "particle_count": 80
    },
    "bg_fire": {
        "intensity": 150, "cooling": 35, "sparking": 120, "delay": 15
    },
    "gravity_fountain": {
        "gravity": 0.15, "bounce": 0.6, "wind": 0.01, "color_mode": 0, "decay_rate": 0.025,
        "max_particles": 40, "enable_ghosting": False, "ghosting_factor": 0.7, "audio_reactive": True
    }
}

for m in ("scan", "diagonal", "radar", "shapes", "wave", "plasma", "spiral", "radial", "noise", "rain_v", "rain_h", "spinner", "edge_walker", "crosshair"):
    MODE_DEFAULTS[m] = {
        "vertical": True, "horizontal": False, "direction": 1,
        "ghosting": 0.7, "random_values": False, "angle": 0.0,
        "speed": 1.0, "audio_reactive": True
    }


def make_param_metadata(name, val):
    if val is None:
        return None
    if isinstance(val, bool):
        return (name, 1 if val else 0, 1, 0, 1)
    lname = name.lower()
    if (lname.startswith("color_") or lname == "color" or lname.endswith("_color") or lname in ("color_p", "color_s", "color_t", "color_q")) and lname not in ("color_mode", "color_interval_ms"):
        return (name, val, "color")
    if isinstance(val, (list, tuple, str)):
        return None
    if lname == "height" or (lname.startswith("height_") and lname[7:].isdigit()):
        return (name, int(val), 2, -137, 137)
    if lname == "pos" or (lname.startswith("pos_") and lname[4:].isdigit()):
        return (name, int(val), 2, 0, 137)
    if lname in ("hue_p", "hue_s", "hue_t", "hue_q"):
        return (name, int(val), 5, -1, 255)
    if "brightness" in lname:
        return (name, int(val), 1, 0, 255)
    if lname == "speed" or lname.endswith("_speed"):
        step = 0.1 if isinstance(val, float) else 1
        return (name, val, step, 0.1, 10.0)
    if lname in ("cooling", "sparking", "intensity"):
        return (name, int(val), 2, 0, 300)
    if lname in ("max_height", "wave_height", "bar_size", "braid_length", "min_len", "max_len", "segment_len"):
        return (name, int(val), 1, 1, 150)
    if lname == "delay" or lname.startswith("delay_") or lname.endswith("_delay"):
        return (name, int(val), 1, 0, 1000)
    if lname == "color_interval_ms" or lname.endswith("_ms"):
        return (name, int(val), 1, 0, 10000)
    if lname == "wait_time" or lname == "time" or (lname.endswith("_time") and lname != "time_sub"):
        return (name, int(val), 1, 0, 10000)
    if lname == "direction":
        return (name, int(val), 2, -1, 1)
    if lname in ("ghosting", "ghosting_factor", "rnd_fac", "friction", "angle", "palette_shift_speed", "hue_offset"):
        step = 5.0 if "angle" in lname else (10.0 if "hue" in lname else 0.05)
        return (name, float(val), step, 0.0, 360.0 if "hue" in lname or "angle" in lname else 1.0)
    if lname in ("arms", "n_dots", "num_snakes", "sections", "cols"):
        return (name, int(val), 1, 1, 36)
    if lname in ("spacing", "cycles", "size"):
        return (name, int(val), 1, 0 if lname == "spacing" else 1, 50)
    if lname in ("mass", "particles", "max_particles"):
        return (name, int(val), 10 if lname == "mass" else 5, 5, 1000)
    if lname == "decay_rate":
        return (name, float(val), 0.005, 0.001, 0.2)
    if lname == "color_mode":
        return (name, int(val), 1, -1, 4)
    if lname == "center_offset":
        return (name, int(val), 1, -69, 69)
    if lname == "gravity":
        return (name, float(val), 0.1, 0.1, 10.0)
    if lname == "wind":
        return (name, float(val), 0.05, -2.0, 2.0)
    if lname == "bounce":
        return (name, float(val), 0.05, 0.0, 1.0)
    if lname == "swallow_radius":
        return (name, float(val), 0.1, 0.5, 10.0)
    if lname in ("n_orbiters", "planet_count"):
        return (name, int(val), 1, 1, 10)
    if lname == "particle_count":
        return (name, int(val), 1, 5, 200)
    if isinstance(val, float):
        return (name, val, 0.1, val - 5.0, val + 5.0)
    if isinstance(val, int):
        return (name, val, 1, val - 100, val + 100)
    return None


def combine_params(scenario, adjusted_params):
    res = scenario.copy()
    
    mode = scenario.get("mode", "")
    defaults = MODE_DEFAULTS.get(mode, {})
    
    if "speed" in adjusted_params:
        spd = adjusted_params["speed"]
        for k in ("scroll_speed", "rotation_speed", "fall_speed"):
            if k in scenario or k in defaults:
                res[k] = spd
                break
        else:
            if "delay" in scenario or "delay" in defaults:
                res["delay"] = int(1000 / spd) if spd > 0 else 1000
            elif "speed" in scenario or "speed" in defaults:
                res["speed"] = spd
                
    for k, v in adjusted_params.items():
        if k == "speed":
            continue
        res[k] = v
        
    for k, v in res.items():
        default_val = defaults.get(k, scenario.get(k))
        if isinstance(default_val, bool):
            res[k] = bool(v)
            
    return {k: v for k, v in res.items() if v is not None}


def rgb_to_hue(rgb):
    if not isinstance(rgb, (list, tuple)) or len(rgb) < 3:
        return 0
    r, g, b = rgb[0], rgb[1], rgb[2]
    mx = r if r > g else g
    mx = mx if mx > b else b
    mn = r if r < g else g
    mn = mn if mn < b else b
    df = mx - mn
    h = 0
    if df != 0:
        if mx == r:
            h = (60 * (g - b)) // df
        elif mx == g:
            h = 120 + (60 * (b - r)) // df
        elif mx == b:
            h = 240 + (60 * (r - g)) // df
        if h < 0:
            h += 360
    return (h * 255) // 360


def make_catalog():
    from effects import matrix_service
    import json
    try:
        with open("scenarios.json", "r", encoding="utf-8") as f:
            scenarios = json.load(f)
    except Exception as e:
        print("Failed to load scenarios.json, fallback to static catalog:", e)
        scenarios = []

    catalog = []
    for sc in scenarios:
        desc = sc.get("desc", sc.get("mode", "UNKNOWN")).upper()
        
        params_list = []
        mode = sc.get("mode", "")
        
        sc_params = MODE_DEFAULTS.get(mode, {}).copy()
        for k, v in sc.items():
            if k in ("mode", "desc"):
                continue
            sc_params[k] = v

        if mode == "static_bars":
            if "height" not in sc_params:
                h_list = sc_params.get("heights")
                sc_params["height"] = h_list[0] if isinstance(h_list, (list, tuple)) and len(h_list) > 0 else -138
            if "pos" not in sc_params:
                p_list = sc_params.get("start_positions")
                sc_params["pos"] = p_list[0] if isinstance(p_list, (list, tuple)) and len(p_list) > 0 else 137
            if "hue_p" not in sc_params:
                c_p = sc_params.get("color_p")
                sc_params["hue_p"] = rgb_to_hue(c_p) if isinstance(c_p, (list, tuple)) else -1
            if "hue_s" not in sc_params:
                c_s = sc_params.get("color_s")
                sc_params["hue_s"] = rgb_to_hue(c_s) if isinstance(c_s, (list, tuple)) else -1
            if "hue_t" not in sc_params:
                c_t = sc_params.get("color_t")
                sc_params["hue_t"] = rgb_to_hue(c_t) if isinstance(c_t, (list, tuple)) else -1
            if "hue_q" not in sc_params:
                c_q = sc_params.get("color_q")
                sc_params["hue_q"] = rgb_to_hue(c_q) if isinstance(c_q, (list, tuple)) else -1
            
            p_list = sc_params.get("start_positions")
            h_list = sc_params.get("heights")
            for i in range(4):
                pos_key = f"pos_{i}"
                if pos_key not in sc_params:
                    sc_params[pos_key] = p_list[i] if isinstance(p_list, (list, tuple)) and len(p_list) > i else 137
                height_key = f"height_{i}"
                if height_key not in sc_params:
                    sc_params[height_key] = h_list[i] if isinstance(h_list, (list, tuple)) and len(h_list) > i else -138
            
        for k, v in sc_params.items():
            if k == "brightness":
                continue
            meta = make_param_metadata(k, v)
            if meta is not None:
                params_list.append(meta)
                
        category = "other"
        if mode in (
            "bars", "center_split", "classic", "fast_bars", "energy_bars",
            "spectrum", "spectrum1", "spectrum_matrix", "waterfall", "wave_audio",
            "static_bars", "radial_audio", "blocks", "vibrant_lights"
        ) or "bars" in mode or "spectrum" in mode:
            category = "bars"
        elif mode in (
            "spring_balls", "pendulum_audio", "planet_orbit", "black_hole",
            "attractor", "gravity_bounce", "gravity_cascade", "gravity_orbiters",
            "gravity_well", "sandclock"
        ) or "gravity" in mode:
            category = "gravity"
        elif mode in (
            "rainbow_effect", "rotating", "plasma", "dna", "gradient_energy",
            "motion_patterns", "pulse"
        ) or "color" in mode or "rainbow" in mode or "plasma" in mode:
            category = "color"
        elif mode in (
            "sparkles", "sparks", "stars", "comet", "rain", "rain_h", "rain_v",
            "fire", "bg_fire", "fire_ice", "fireworks", "storm", "storm2", "noise",
            "beat_flash", "beat_impact", "bpm_pulse", "flux_onset"
        ) or "spark" in mode or "fire" in mode or "rain" in mode or "storm" in mode or "flash" in mode:
            category = "spark"
            
        catalog.append({
            "name": desc,
            "category": category,
            "mode": mode,
            "params": tuple(params_list),
            "scenario": sc,
            "func": lambda b, p, sc=sc: matrix_service([b], **combine_params(sc, p))
        })
        
    if not catalog:
        catalog = [
            {"name": "ANALOG CLOCK", "category": "other",
             "params": (("show_marks", 1, 1, 0, 1), ("target_brightness", 63, 3, 0, 255)),
             "func": lambda b, p: b.render_analog_clock(show_marks=bool(p.get("show_marks", True)), h_width=1.2, m_width=1.0, s_width=0.8, target_brightness=p.get("target_brightness", 63), auto_brightness=True)},
            {"name": "BARS HORIZ", "category": "bars",
             "params": (("bar_size", 8, 2, 4, 20), ("spacing", 2, 1, 0, 10), ("show_peaks", 1, 1, 0, 1), ("reverse_bands", 1, 1, 0, 1), ("enable_symmetric", 0, 1, 0, 1), ("enable_peak_flash", 1, 1, 0, 1), ("center_offset", -10, 1, -50, 50)),
             "func": lambda b, p: b.render_bars(orientation="h", bar_size=p.get("bar_size", 8), spacing=p.get("spacing", 2), show_peaks=bool(p.get("show_peaks", True)), reverse_bands=bool(p.get("reverse_bands", True)), enable_symmetric=bool(p.get("enable_symmetric", False)), enable_peak_flash=bool(p.get("enable_peak_flash", True)), center_offset=p.get("center_offset", -10))}
        ]
        
    return tuple(catalog)


def configure_display(c):
    c.led2.init_display_system(rows=138, cols=4)
    ds = c.led2.display_system


    ds.set_zones([("time", 1, 45), ("s", 49, 137), ("status", 1, 137), ("s2", 1, 137)])
    ds.set_zone_colors("time", fg=(c.palette[1230], c.palette[1231], c.palette[1232]))
    ds.enable_colon_blink("time", period_ms=500)
    ds.set_zone_presentation("time", presentation="st", animation="su", duration_ms=400)
    ds.set_zone_presentation("s", presentation="sq", animation="ft", duration_ms=300)
    
    ds.set_zone_sequence_duration("s", 10000)
    ds.set_zone_sequence_duration("s2", 10000)
    ds.set_zone_scroll("status", enabled=True, mode='p', delay_ms=150, pixel_step=1, start_hold_ms=2500, end_hold_ms=3000)
    ds.set_zone_scroll("s", enabled=True, mode='p', delay_ms=150, pixel_step=1, start_hold_ms=2500, end_hold_ms=2500)
    ds.set_zone_scroll("s2", enabled=True, mode='p', delay_ms=150, pixel_step=1, start_hold_ms=2500, end_hold_ms=2500)
    
    ds.set_zone_presentation("status", presentation="st", animation="f", duration_ms=150)
    ds.set_zone_enabled("status", False)
    ds.set_led_clear_before_copy(False)
    ds.set_copy_black_pixels(True)
    return ds


def set_overlay_mode(c, ds, app):
    if not ds:
        return
    mode = app.led2.mode_name()
    if mode == "TIME":
        c.led2.enable_text_overlay()
        ds.set_copy_black_pixels(True)
        ds.set_led_clear_before_copy(True)
        sub = app.time_sub
        if sub == "TIME_ONLY":
            ds.set_zone_enabled("time", True)
            ds.set_zone_enabled("s", False)
            ds.set_zone_enabled("s2", False)
            app.s2 = False
        elif sub == "TIME_CUSTOM":
            ds.set_zone_enabled("time", True)
            ds.set_zone_enabled("s", True)
            ds.set_zone_enabled("s2", False)
            app.s2 = False
        elif sub == "CUSTOM":
            ds.set_zone_enabled("time", False)
            ds.set_zone_enabled("s", False)
            ds.set_zone_enabled("s2", True)
            app.s2 = True
    else:
        ds.set_zone_enabled("time", False)
        ds.set_zone_enabled("s", False)
        ds.set_zone_enabled("s2", False)
        c.led2.disable_text_overlay()
        ds.set_copy_black_pixels(False)
        ds.set_led_clear_before_copy(False)


def update_overlay(c, ds, app, ir_reader=None):
    if not ds:
        return
    
    now = time.ticks_ms()

    if ir_reader is not None and getattr(ir_reader, "learn_mode", False):
        raw_msg = ir_reader.learner.prompt()
    else:
        raw_msg = app.current_ui_message(now)

    if raw_msg:
        status_msg = raw_msg + " " * 4
        ds.set_zone_messages("status", [status_msg])
        ds.set_zone_colors("status", fg=(220, 220, 220))
        ds.set_zone_enabled("status", True)
    else:
        ds.set_zone_colors("time", fg=(c.palette[1230], c.palette[1231], c.palette[1232]))
        ds.set_zone_enabled("status", False)

    zone = ""
    if ds.get_zone_enabled("s2"):
        zone = "s2"
    else:
        zone = "s"

    b = c.process_lux(c.lux, 20)
    ds.set_brightness(max(3, b))

    event_name = None
    if c.is_holiday_today[0]:
        event_name = c.is_holiday_today[1]
    elif c.is_special_today[0]:
        event_name = c.is_special_today[1]
    temp = 0
    temp = c.temperature + TEMP_OFFSET
    if event_name is None:
        sensor_msgs = [
            "{}".format(c.get_name_of_the_day(c.weekday)),
            "{:02d}:{:02d}:{:4d}".format(c.day, c.month, c.year),
            "T-{:.1f}`".format(temp),
            "W-{:.1f}%".format(c.humidity),
            "C-{:d} HPA".format(c.pressure),
            "S-{:.1f} LUX".format(c.lux)
        ]
    else:
        sensor_msgs = [
            "{}".format(event_name),
            "{}".format(c.get_name_of_the_day(c.weekday)),
            "{:02d}:{:02d}:{:4d}".format(c.day, c.month, c.year),
            "T-{:.1f}`".format(temp),
            "W-{:.1f}%".format(c.humidity),
            "C-{:d} HPA".format(c.pressure),
            "S-{:.1f} LUX".format(c.lux)
        ]

    if c.minutes % 10 in (0, 1) and getattr(c, "weather_temp", None) is not None:
        PADDING_SPACES = 3
        max_len = 63
        
        def prepare_weather_msg(msg):
            padded = msg + " " * PADDING_SPACES
            return padded[:max_len]
            
        msg1 = "TZEW-{:.1f}`".format(c.weather_temp)
        sensor_msgs.append(prepare_weather_msg(msg1))
        msg12 = "TODC-{:.1f}`".format(c.weather_feels_like)
        sensor_msgs.append(prepare_weather_msg(msg12))
        
        sanitized_description = c.strip_polish_diacritics(c.weather_description).upper()
        wind_dir = c.get_polish_wind_direction(c.weather_wind_dir)
        msg2 = "WIATR-{}-{:.1f} KM/H".format(wind_dir, c.weather_wind_speed*3.6)
        sensor_msgs.append(prepare_weather_msg(msg2))
        msg22 = "-{}-".format(sanitized_description)
        sensor_msgs.append(prepare_weather_msg(msg22))
        
        sunrise_tm = c.convert_unix_to_local(c.weather_sunrise)
        sunset_tm = c.convert_unix_to_local(c.weather_sunset)
        msg3 = "WSCH-a-{:02d}:{:02d}".format(sunrise_tm[3], sunrise_tm[4])
        sensor_msgs.append(msg3)
        msg31 = "ZACH-e-{:02d}:{:02d}".format(sunset_tm[3], sunset_tm[4])
        sensor_msgs.append(msg31)
                
        msg4 = "{:02d}:{:02d}:{:02d}".format(c.hour, c.minutes, c.seconds)
        sensor_msgs.append(msg4)


    if c.is_holiday_today[0] or c.is_special_today[0]:
        if ds.zones[3].sequence_index < 3:
            color_no = 0
            if c.is_special_today[0]:
                if ("URODZINY" or "ROCZNICA") in c.is_special_today[1]:
                    color_no = 960
                else:
                    color_no =741
            ds.set_zone_presentation(zone, presentation="sq", animation="sl", duration_ms=300)
        elif ds.zones[3].sequence_index > 6:
            color_no = 1500
            ds.set_zone_presentation(zone, presentation="sq", animation="su", duration_ms=300)
        else:
            color_no = 51
            ds.set_zone_presentation(zone, presentation="sq", animation="sd", duration_ms=300)
    else:
        if ds.zones[3].sequence_index > 5:
            color_no = 1500
            ds.set_zone_presentation(zone, presentation="sq", animation="sd", duration_ms=300)
        else:
            color_no = 51
            ds.set_zone_presentation(zone, presentation="sq", animation="sr", duration_ms=300)

    ds.set_zone_colors(
            zone,
            fg=(c.palette[color_no], c.palette[color_no + 1], c.palette[color_no + 2]),
            bg=(0, 0, 0)
            )
    ds.set_zone_messages(zone, sensor_msgs)

    ds.update(c)


def clear_and_write(led):
    if led:
        led.aled_object.clear()
        led.aled_object.write()


def status_message(app, action=None):
    menu = app.focused()
    led_name = "L1" if app.focus_led == 1 else "L2"
    eff = menu.current_effect()
    param = menu.param_label()
    mode = menu.mode_name()
    if mode == "EFFECTS":
        msg = "%s %s %s" % (led_name, eff["name"], param)
    else:
        msg = "%s %s %s %s" % (led_name, mode, eff["name"], param)
        
    if action == "AUTO_TOGGLE":
        msg = "AUTO %s %dS" % ("ON" if app.auto_enabled else "OFF", app.auto_interval_ms // 1000)
    elif action in ("AUTO_INTERVAL_UP", "AUTO_INTERVAL_DOWN"):
        msg = "AUTO INTERVAL %dS" % (app.auto_interval_ms // 1000)
    elif action in ("BRIGHTNESS_UP", "BRIGHTNESS_DOWN"):
        msg = "%s BRIGHT %d" % (led_name, menu.brightness)
    elif action == "LED2_TIME":
        if app.focus_led == 2:
            sub_labels = {"TIME_ONLY": "L2 CLOCK", "CUSTOM": "L2 SENSORS", "TIME_CUSTOM": "L2 CLOCK+SENS"}
            msg = sub_labels.get(app.time_sub, "L2 TIME")
    elif action == "LED2_TIME_FX":
        if app.focus_led == 2:
            msg = "L2 CLOCK+SENS"
    elif action == "LED2_FX":
        if app.focus_led == 2:
            msg = "L2 FX"
    return msg


@micropython.native
def poll_action(c, app, ir_reader=None):
    cmd = c.poll_input()
    action = _BUTTON_TO_ACTION.get(cmd) if cmd is not None else None

    remote_action = ir_action(ir_reader)
    if remote_action:
        action = remote_action
        
    return action


def apply_state_result(c, app, bars1, bars2, result, action=None):
    if result in ("effect", "param_timeout"):
        if app.focus_led == 1:
            bars1.reset_effect_state()
            c.led1.aled_object.clear()
        else:
            bars2.reset_effect_state()
            c.led2.aled_object.clear()

        focused_menu = app.focused()
        eff = focused_menu.current_effect()
        print("[Effect Switch] LED%d -> %s (Index: %d, Params: %s)" % (app.focus_led, eff["name"], focused_menu.effect_index, focused_menu.params))

    elif result == "mode":
        if app.focus_led == 1:
            c.led1.aled_object.clear()
        else:
            c.led2.aled_object.clear()
        print("[Mode Change] LED%d -> Mode: %s" % (app.focus_led, app.focused().mode_name()))
    
    now = time.ticks_ms()
    app.set_ui_message(status_message(app, action), now, UI_MESSAGE_MS)
    if action != "AUTO_STEP":
        if result == "param_select":
            c.beep(10)
            time.sleep_ms(40)
            c.beep(10)
        elif result == "effect" and action in ("TOGGLE_EDIT_MODE", "NEXT_PARAM_LONG"):
            c.beep(40)
        else:
            c.beep(10 if result != "focus" else 20)
        if result in ("param", "param_select"):
            print("[Param Change] Adjusted params for", app.focused().current_effect()["name"], ":", app.focused().params)
    else:
        if result in ("param", "param_select"):
            print("[Param Auto] Adjusted params for", app.focused().current_effect()["name"], ":", app.focused().params)
    gc.collect()


def apply_action(c, app, bars1, bars2, action):
    result = app.handle_action(action)
    if not result:
        return
    apply_state_result(c, app, bars1, bars2, result, action)


@micropython.native
def render_led1(c, app, bars1):
    mode = app.led1.mode_name()
    if mode == "OFF" or not c.led1.led_active:
        clear_and_write(c.led1)
        return
    if mode == "TIME" and not "CLOCK" in app.led1.current_effect().get("name", ""):
        app.led1.set_mode("EFFECTS")
        mode = "EFFECTS"
    bars1.brightness = 255
    app.led1.current_effect()["func"](bars1, app.led1.params)
    if app.led1.brightness < 255:
        c.led1.aled_object.apply_br_to_buffer(c.gamma_table, app.led1.brightness)
    c.led1.aled_object.write()


@micropython.native
def render_led2(c, app, bars2, ds, ir_reader=None):
    mode = app.led2.mode_name()
    if mode == "OFF" or not c.led2.led_active:
        clear_and_write(c.led2)
        return

    now = time.ticks_ms()
    is_learning = ir_reader is not None and getattr(ir_reader, "learn_mode", False)
    status_active = bool(app.current_ui_message(now)) or is_learning

    if mode == "EFFECTS":
        bars2.brightness = 255
        app.led2.current_effect()["func"](bars2, app.led2.params)
        if app.led2.brightness < 255:
            c.led2.aled_object.apply_br_to_buffer(c.gamma_table, app.led2.brightness)
        if ds:
            ds.set_zone_enabled("time", False)
            ds.set_zone_enabled("s", False)
            ds.set_zone_enabled("s2", False)
            if status_active:
                c.led2.enable_text_overlay()
                ds.set_copy_black_pixels(False)
                ds.set_led_clear_before_copy(False)
                update_overlay(c, ds, app, ir_reader)
                app.status_was_active = True
            else:
                if getattr(app, "status_was_active", False):
                    c.led2.aled_object.clear()
                    app.status_was_active = False
                ds.set_zone_enabled("status", False)
                c.led2.disable_text_overlay()
    else:  # TIME
        set_overlay_mode(c, ds, app)
        update_overlay(c, ds, app, ir_reader)

    c.led2.aled_object.write()


def main():
    st = 0
    from init import Controller
    from effects import AudioEffects

    c = Controller()
    c.configure_audio(512, 12, 0.92, 0.99, 0.20, 0.00001, 0.0003)

    for btn in (c.b_left, c.b_right, c.b_plus, c.b_minus, c.b_confirm, c.b_l1, c.b_l2):
        if btn is not None:
            btn.long_press_time(600)

    ae2 = AudioEffects(
        c, c.led2,
        rows=138, cols=4,
        smoothing=0.7,
        peak_color=(255, 255, 255),
        peak_minimum=1.0, brightness=255,
    )
    ae2.noise_threshold = 8

    ae1 = AudioEffects(
        c, c.led1,
        rows=19, cols=19,
        smoothing=0.7,
        brightness=255,
    )
    ae1.noise_threshold = 8

    ds = configure_display(c)
    catalog = make_catalog()
    
    app = AppState(catalog, c)
    
    print("[Startup] LED1 Initial Effect: %s (Params: %s)" % (app.led1.current_effect()["name"], app.led1.params))
    print("[Startup] LED2 Initial Effect: %s (Params: %s)" % (app.led2.current_effect()["name"], app.led2.params))
    
    ir_reader = IRActionReader(c, config_ready=IR_CONFIG_READY, map_file=IR_MAP_FILE)
    if not IR_CONFIG_READY:
        print(ir_reader.learner.prompt())

    web_server = None
    try:
        from web_server import NonBlockingWebServer
        web_server = NonBlockingWebServer(
            c, app, ae1, ae2,
            state_callback=lambda res, act: apply_state_result(c, app, ae1, ae2, res, act)
        )
    except Exception as e:
        print("[WebServer] Failed to initialize web server:", e)

    last_led2_frame = time.ticks_ms() - OVERLAY_FRAME_MIN_TIME
    
    while True:
        frame_start = time.ticks_ms()
        app.beat_detected = True
        
        if web_server:
            web_server.poll()
            
        action = poll_action(c, app, ir_reader)
        apply_action(c, app, ae1, ae2, action)
        auto_result = app.auto_step(frame_start)
        if auto_result:
            apply_state_result(c, app, ae1, ae2, auto_result, "AUTO_STEP")

        render_led1(c, app, ae1)
        led2_mode = app.led2.mode_name()
        if led2_frame_due(led2_mode, frame_start, last_led2_frame):
            render_led2(c, app, ae2, ds, ir_reader)
            if led2_mode == "TIME":
                last_led2_frame = frame_start

        elapsed = ticks_diff(time.ticks_ms(), frame_start)
        if elapsed < FRAME_MIN_TIME:
            time.sleep_ms(FRAME_MIN_TIME - elapsed)
            
        if c.pir.state_value() != 0:    
            c.clear_pir()
            
        if c.sleepy(): 
            c.go_sleep()


if __name__ == "__main__":
    main()
