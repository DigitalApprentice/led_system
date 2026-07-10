"""
IR remote mapping helper for audio_bars_exibition_3.py.

Config file format:
ACTION|PROTOCOL|ADDRESS|COMMAND|RAW
"""

IR_LEARN_SEQUENCE = (
    ("LED1_POWER", "top-left black power: LED1 on/off"),
    ("AUTO_TOGGLE", "top-center A: auto effect rotation"),
    ("LED2_POWER", "top-right red power: LED2 on/off"),
    ("CATEGORY_COLOR", "row2-left color wheel: color/rainbow effects"),
    ("RANDOMIZE", "row2-center palette: randomize current params"),
    ("CATEGORY_SPARK", "row2-right star: spark/star effects"),
    ("BRIGHTNESS_DOWN", "row3-left dim sun: brightness down"),
    ("FOCUS_NEXT", "row3-center window/mirror: focus LED1/LED2"),
    ("BRIGHTNESS_UP", "row3-right bright sun: brightness up"),
    ("SPEED_DOWN", "row4-left speed: speed down"),
    ("PARAM_UP", "triangle up: parameter value up"),
    ("SPEED_UP", "row4-right speed: speed up"),
    ("PREV_EFFECT", "arrow left: previous effect"),
    ("NEXT_PARAM", "center picture: next parameter"),
    ("NEXT_EFFECT", "arrow right: next effect"),
    ("AUTO_INTERVAL_DOWN", "spark pause: auto interval down"),
    ("PARAM_DOWN", "triangle down: parameter value down"),
    ("AUTO_INTERVAL_UP", "spark play: auto interval up"),
    ("CATEGORY_BARS", "music 1: bars category"),
    ("CATEGORY_GRAVITY", "music 2: gravity category"),
    ("CATEGORY_OTHER", "music 3: other category"),
    ("LED2_TIME", "bottom -1H: LED2 time mode"),
    ("LED2_TIME_FX", "bottom -2: LED2 time+fx mode"),
    ("LED2_FX", "bottom -3H: LED2 fx mode"),
)

NEC_COMMAND_ACTIONS = {
    0x45: "PARAM_UP",
    0x48: "PARAM_UP",
    0x46: "PARAM_DOWN",
    0x58: "PARAM_DOWN",
    0x44: "PREV_EFFECT",
    0x78: "PREV_EFFECT",
    0x43: "NEXT_EFFECT",
    0xF8: "NEXT_EFFECT",
    0x40: "NEXT_PARAM",
    0x30: "NEXT_PARAM",
    0x07: "FOCUS_NEXT",
    0x10: "FOCUS_NEXT",
    0x15: "NEXT_MODE",
    0x90: "NEXT_MODE",
}

LED_RAW_ACTIONS = {
    0x1FE48B7: "PARAM_UP",
    0x1FE58A7: "PARAM_DOWN",
    0x1FE7887: "PREV_EFFECT",
    0x1FEF807: "NEXT_EFFECT",
    0x1FE30CF: "NEXT_PARAM",
    0x1FE10EF: "FOCUS_NEXT",
    0x1FE906F: "NEXT_MODE",
}


def _ticks_ms():
    try:
        import time
        return time.ticks_ms()
    except AttributeError:
        import time
        return int(time.time() * 1000)


def _ticks_diff(now, last):
    try:
        import time
        return time.ticks_diff(now, last)
    except AttributeError:
        return now - last


def ir_record_key(record):
    if not record:
        return None
    protocol = record.get("protocol")
    raw = int(record.get("raw", 0))
    if protocol == "NEC":
        return ("NEC", int(record.get("address", -1)), int(record.get("command", -1)), raw)
    return ("LED", -1, -1, raw)


def default_ir_map():
    out = {}
    for cmd, action in NEC_COMMAND_ACTIONS.items():
        out[("NEC", -1, cmd, 0)] = action
    for raw, action in LED_RAW_ACTIONS.items():
        out[("LED", -1, -1, raw)] = action
    return out


def parse_ir_map(lines):
    mapping = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) != 5:
            continue
        action, protocol, address, command, raw = parts
        try:
            key = (protocol, int(address), int(command), int(raw))
        except ValueError:
            continue
        mapping[key] = action
    return mapping


def format_ir_map(mapping):
    lines = [
        "# IR map for audio_bars_exibition_3.py",
        "# ACTION|PROTOCOL|ADDRESS|COMMAND|RAW",
    ]
    for key, action in sorted(mapping.items(), key=lambda item: item[1]):
        protocol, address, command, raw = key
        lines.append("%s|%s|%d|%d|%d" % (action, protocol, address, command, raw))
    return "\n".join(lines) + "\n"


def load_ir_map(path):
    try:
        with open(path, "r") as f:
            mapping = parse_ir_map(f.readlines())
        return mapping if mapping else default_ir_map()
    except OSError:
        return default_ir_map()


def save_ir_map(mapping, path):
    try:
        with open(path, "w") as f:
            f.write(format_ir_map(mapping))
            try:
                f.flush()
                import os
                os.sync()
            except:
                pass
        print("IR map saved to:", path)
    except Exception as e:
        print("Error saving IR map:", e)


def lookup_ir_action(record, mapping):
    key = ir_record_key(record)
    if not key:
        return None
    action = mapping.get(key)
    if action:
        return action
    protocol, _address, command, raw = key
    if protocol == "NEC":
        return mapping.get(("NEC", -1, command, 0))
    return mapping.get(("LED", -1, -1, raw))


def decode_ir_record(record, mapping=None):
    if not record:
        return None
    if mapping is not None:
        return lookup_ir_action(record, mapping)
    protocol = record.get("protocol")
    if protocol == "NEC":
        return NEC_COMMAND_ACTIONS.get(record.get("command"))
    return LED_RAW_ACTIONS.get(record.get("raw"))


class IRMapLearner:
    def __init__(self, sequence=IR_LEARN_SEQUENCE):
        self.sequence = sequence
        self.index = 0
        self.map = {}

    def done(self):
        return self.index >= len(self.sequence)

    def learn(self, record):
        if self.done():
            return None
        key = ir_record_key(record)
        if not key:
            return None
        item = self.sequence[self.index]
        action = item[0] if isinstance(item, tuple) else item
        self.map[key] = action
        self.index += 1
        return action

    def prompt(self):
        if self.done():
            return "IR MAP DONE"
        item = self.sequence[self.index]
        action = item[0] if isinstance(item, tuple) else item
        label = item[1] if isinstance(item, tuple) and len(item) > 1 else action
        return "IR LEARN %s" % label


class IRActionReader:
    def __init__(self, controller, config_ready=True, map_file="ir_map.conf", repeat_ms=100):
        self.controller = controller
        self.repeat_ms = repeat_ms
        self.last_key = None
        self.last_time = 0
        self.config_ready = config_ready
        self.learn_mode = not config_ready
        self.map_file = map_file
        self.learner = IRMapLearner() if self.learn_mode else None
        self.mapping = load_ir_map(map_file) if config_ready else {}

    def read(self):
        ir = getattr(self.controller, "ir_core1", None)
        if ir is not None:
            try:
                if not ir.available():
                    return None
                record = ir.read()
            except Exception:
                record = None
            key = ir_record_key(record)
            if not key:
                return None
            is_long = bool(record.get("long_press"))
            now = _ticks_ms()
            if key == self.last_key and not is_long and _ticks_diff(now, self.last_time) < self.repeat_ms:
                return None
            self.last_key = key
            self.last_time = now

            if self.learn_mode:
                action = self.learner.learn(record)
                if action:
                    save_ir_map(self.learner.map, self.map_file)
                    print("IR mapped:", action, "at key", key)
                    if self.learner.done():
                        print("IR mapping complete. Set IR_CONFIG_READY = True.")
                return None

            action = decode_ir_record(record, self.mapping)
            if not action:
                print("IR unmapped:", record)
                return None
            if record.get("long_press"):
                return action + "_LONG"
            return action

        value = self.controller.get_ir_command()
        if value:
            fallback = {
                1: "PARAM_UP", 2: "PARAM_DOWN", 3: "PREV_EFFECT", 4: "NEXT_EFFECT",
                5: "NEXT_PARAM", 10: "FOCUS_NEXT", 11: "NEXT_MODE",
            }
            return fallback.get(value)
        return None
