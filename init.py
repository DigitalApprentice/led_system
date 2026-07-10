"""
CLeds Controller System V2 - Main Classes
=========================================

CORE PARAMETERS & RANGES:
-------------------------
- CPU Frequency: 240 MHz
- LED Brightness: 0 - 255 (Device level)
- Sensors:
    - Temperature: Float (Celsius)
    - Humidity: Float (%)
    - Pressure: Float (hPa)
    - Luminance (lux): Float 0 - 65535 (BH1750)
- Input Commands (CMD_*): 0 - 11 (from switches.py)
- RTC: year, month, day, weekday, hour, minutes, seconds

For detailed FFT configuration and Spectral Feature Map, 
see documentation inside Controller.set_i2s()
"""

from machine import Pin, SoftI2C, I2S, RTC, Timer, freq, lightsleep
from lib.switches import (
    b_refresh, CMD_UP, CMD_UP_L, CMD_DOWN, CMD_DOWN_L, CMD_LEFT, CMD_LEFT_L,
    CMD_RIGHT, CMD_RIGHT_L, CMD_CONFIRM, CMD_CONFIRM_L, CMD_L1, CMD_L1_L,
    CMD_L2, CMD_L2_L
)
from esp32 import wake_on_ext0, WAKEUP_ANY_HIGH
import gc
import micropython
import math
import time
import ntptime
from lib import wifi_manager
from aleds_rgb import AledsRgb

# ============================================================================
# HARDWARE PIN CONFIGURATION
# ============================================================================
PIN_LED1           = 2
PIN_LED2           = 42
PIN_I2C_SCL        = 47
PIN_I2C_SDA        = 21
PIN_I2S_SCK        = 13
PIN_I2S_WS         = 12
PIN_I2S_SD         = 14
PIN_IR_RX          = 39
PIN_BUZZER         = 45
PIN_BUTTON_L       = 7
PIN_BUTTON_R       = 4
PIN_BUTTON_MINUS   = 5
PIN_BUTTON_PLUS    = 6
PIN_BUTTON_C       = 15
PIN_BUTTON_L1      = 41
PIN_BUTTON_L2      = 40
PIN_BUTTON_PIR     = 20

# Module-level lookup tables for IR mapping (defined once, outside class)
_IR_KEYS = (0x1FE48B7, 0x1FE58A7, 0x1FE7887, 0x1FEF807, 0x1FE30CF, 0x1FE10EF, 0x1FE906F)
_IR_VALS = bytearray([1, 2, 3, 4, 5, 10, 11])

class Led:
    def __init__(self, id, aled):
        self.id = id
        self.aled_object = aled
        self.device_brightness = 255
        self.led_active = True
        self.led_buffer = aled.aled_buffer
        self.display_system = None
        self.text_overlay_enabled = False
        self.cols = 0
        self.rows = 0
        self.length = 0

    def set_brightness(self, brightness):
        self.device_brightness = max(0, min(255, brightness))

    def init_display_system(self, rows=138, cols=4, render_direction=0, spacing=2):


        try:
            from leddisplay import LEDDisplaySystem
            if self.cols == 0: self.cols = cols
            if self.rows == 0: self.rows = rows
            self.display_system = LEDDisplaySystem(self, rows=self.rows, cols=self.cols, render_direction=render_direction, spacing=spacing)
            return True
        except Exception:
            self.display_system = None
            return False

    def overlay_text(self):
        if self.display_system and self.text_overlay_enabled:
            try:
                if hasattr(self.display_system, 'renderer'):
                    self.display_system.renderer.copy_to_led_buffer(
                        self.display_system.renderer.fb_rows,
                        self.display_system.renderer.fb_cols
                    )
                elif hasattr(self.display_system, 'copy_to_led_buffer'):
                    self.display_system.copy_to_led_buffer()
            except Exception:
                pass

    def enable_text_overlay(self):
        """Enable text overlay on effects."""
        if self.display_system is None:
            print('WARNING: display_system not initialized. Call init_display_system() first.')
            return False
        self.text_overlay_enabled = True
        return True

    def disable_text_overlay(self):
        """Disable text overlay on effects."""
        self.text_overlay_enabled = False
        return True

    def set_led_active(self, active=True):
        self.led_active = bool(active)


class Controller:

    def __init__(self):
        freq(240000000)
        self.first_run = True
        self.ds_set = False
        self.rtc_set = False
        self.time_refreshed = False
        self.sensor_refreshed = False
        self.timer = None
        self.set_initial_date_and_time()
        self.palette = bytearray()
        self.pal_length = 0
        self.gamma_factor = 2.4
        self.gamma_table = self.generate_gamma_table(self.gamma_factor)
        self.set_palette()
        self.ir_refreshed = False
        self.clock_led = True
        self.sensor_led = True
        self.buzzer_active = True
        self.controller_reset = False
        self.pir_time = time.ticks_ms()
        self.sleep = False
        self.pir_delay = 1800000
        # Initialize sensor data with defaults to prevent AttributeError
        self.temperature = 0
        self.humidity = 0
        self.pressure = 0
        self.lux = 100
        self.smoothed_lux = float(self.lux)
        self.lux_alpha = 0.4
        self.last_brightness = 255
        self.is_holiday_today = ()
        self.is_special_today = ()
        self.init_hardware()
        self.init_wifi_and_sync()
        self.holidays(self.year)
        self.is_holiday_today = self.is_holiday(self.day, self.month, self.year)
        self.is_special_today = self.is_special(self.day, self.month, self.year)

    def generate_gamma_table(self, gamma_value):
        table = bytearray(256)

        for i in range(256):
            normalized = i / 255.0

            corrected = pow(normalized, gamma_value) * 255.0

            table[i] = min(255, round(corrected))

        return table

    def update_gamma(self, gamma_factor):
        """Allows you to change the 'vibe' on the fly"""
        self.gamma_table = self.generate_gamma_table(gamma_factor)

    def set_palette(self, length=552):
        self.pal_length = length
        self.palette = bytearray(length * 3)

        for i in range(length):
            h = i / length

            # Algorytm HSV do RGB (uproszczony dla S=1, V=1)
            i_sect = int(h * 6)
            f = (h * 6) - i_sect
            q = int(255 * (1 - f))
            t = int(255 * f)

            if i_sect == 0:
                r, g, b = 255, t, 0
            elif i_sect == 1:
                r, g, b = q, 255, 0
            elif i_sect == 2:
                r, g, b = 0, 255, t
            elif i_sect == 3:
                r, g, b = 0, q, 255
            elif i_sect == 4:
                r, g, b = t, 0, 255
            else:
                r, g, b = 255, 0, q

            idx = i * 3
            self.palette[idx] = r
            self.palette[idx + 1] = g
            self.palette[idx + 2] = b

    def set_lab_palette(self, length: int = 414, L=55, C=100):
        # --- LAB -> XYZ -> RGB helpers ---
        self.pal_length = length
        self.palette = bytearray(length * 3)
        def lab_to_xyz(L, a, b):
            # D65 reference white
            ref_X, ref_Y, ref_Z = 95.047, 100.000, 108.883

            fy = (L + 16) / 116
            fx = a / 500 + fy
            fz = fy - b / 200

            def f_inv(t):
                return t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787

            x = ref_X * f_inv(fx)
            y = ref_Y * f_inv(fy)
            z = ref_Z * f_inv(fz)

            return x, y, z
        def xyz_to_rgb(x, y, z):
            # normalize
            x /= 100
            y /= 100
            z /= 100
            r = x * 3.2406 + y * -1.5372 + z * -0.4986
            g = x * -0.9689 + y * 1.8758 + z * 0.0415
            b = x * 0.0557 + y * -0.2040 + z * 1.0570
            def gamma_correct(c):
                return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
            r = gamma_correct(r)
            g = gamma_correct(g)
            b = gamma_correct(b)
            return (
                int(max(0, min(1, r)) * 255),
                int(max(0, min(1, g)) * 255),
                int(max(0, min(1, b)) * 255),
            )
        def lab_to_rgb(L, a, b):
            return xyz_to_rgb(*lab_to_xyz(L, a, b))

        def generate_lab_palette(steps, L,C ):
            color = (0,0,0)
            for i in range(steps):
                h = (i / steps) * 2 * math.pi
                a = math.cos(h) * C
                b = math.sin(h) * C
                color = lab_to_rgb(L, a, b)
                idx = i * 3
                self.palette[idx] = color[0]
                self.palette[idx + 1] = color[1]
                self.palette[idx + 2] = color[2]

        generate_lab_palette(length,L,C)

    def clamp_color(self, color: tuple) -> tuple:
        """Clamp color values to 0-255 range."""
        return tuple(max(0, min(255, int(c))) for c in color[:3])
    def blend_colors(self, color1: tuple, color2: tuple, amount: float = 0.5) -> tuple:
        amount = max(0.0, min(1.0, amount))
        r = int(color1[0] + (color2[0] - color1[0]) * amount)
        g = int(color1[1] + (color2[1] - color1[1]) * amount)
        b = int(color1[2] + (color2[2] - color1[2]) * amount)
        return self.clamp_color((r, g, b))

    def reverse(self):
        """Reverse palette order in-place."""
        new_data = bytearray(len(self.palette))
        for i in range(self.pal_length):
            src_idx = (self.pal_length - 1 - i) * 3
            dst_idx = i * 3
            new_data[dst_idx] = self.palette[src_idx]
            new_data[dst_idx + 1] = self.palette[src_idx + 1]
            new_data[dst_idx + 2] = self.palette[src_idx + 2]
        self.palette[:] = new_data

    def rotate(self, steps: int = 1):
        if self.pal_length == 0: return
        steps = steps % self.pal_length
        if steps == 0: return
        byte_steps = steps * 3
        self.palette[:] = self.palette[-byte_steps:] + self.palette[:-byte_steps]

    def init_hardware(self):
        """Initialize all hardware components"""
        self.gc_collect()
        try:
            self.set_led2(4, 138)
            print("Led2: Free memory", gc.mem_free(), "B")
        except MemoryError:
            print("Led2 nie zainicjalizowane - Memory error")
            print("Free memory = ",gc.mem_free(),"B")
            self.led2 = None
            pass
        self.gc_collect()
        try:
            self.set_led1(1, 72)
            print("Led1: Free Memory", gc.mem_free(), "B")
        except MemoryError:
            print("Led1 nie zainicjalizowane - Memory Error")
            print("Free memory = ", gc.mem_free(),"B")
            self.led1 = None
        
        self.set_i2c()
        self.set_ds()
        self.set_bme()
        self.set_rtc()
        self.set_bh1750()
        self.set_ir()
        self.set_i2s()
        self.set_buzzer()
        self.set_buttons()
        self.set_timer()

        self.gc_collect()
    
    def set_timer(self, period=1000, active=True):
        """Configure timer"""
        self.timer = Timer(0)
        if active:
            self.timer.init(period=period, mode=Timer.PERIODIC,
                            callback=lambda t: self.get_data())
        else:
            self.timer.deinit()

    def set_i2s(self):
        try:
            import fft_core1 as fft
            try:
                fft.stop()
            except:
                pass
            if hasattr(self, '_last_audio_cfg'):
                self.configure_audio(*self._last_audio_cfg)
            else:
                self.configure_audio()
            fft.start(
                PIN_I2S_SCK,
                PIN_I2S_WS,
                PIN_I2S_SD,
                44100
            )

            self.mv_bands = memoryview(fft.bands())
            self.mv_mag   = memoryview(fft.magnitudes())
            self.mv_feat  = memoryview(fft.features())
            self._fft_mod = fft
            """
            FFT CORE1 CONFIGURATION & DATA MAP
            ==================================
            
            1. fft.configure(size, bands, decay, agc_dec, beat_thr, agc_floor, gate)
            ----------------------------------------------------------------------
            - size [int]: 256, 512, 1024. Higher = more precision, slower.
            - bands [int]: 1 to 24. Number of logarithmic frequency bands.
            - decay [float]: Individual bin peak decay (smooths bars). Default: 0.92
            - agc_dec [float]: Gain recovery rate. Lower = faster gain boost. Default: 0.99
            - beat_thr [float]: Sensitivity for beat detection. Default: 0.25
            - agc_floor [float]: INMP441 raw mags ~0.003, set ≤0.001. Default: 0.00001
            - gate [float]: Must be < max_mag_raw (~0.003 for INMP441). Default: 0.0001

            2. fft.features() - Memory Map (56 bytes)
            -----------------------------------------
            [Type]  [Name]           [Offset]  [Range/Description]
            float32 energy           0         0.0 - 1.0: Frame RMS energy
            float32 bass             4         0.0 - 1.0: 20-300 Hz
            float32 mid              8         0.0 - 1.0: 300-4000 Hz
            float32 treble           12        0.0 - 1.0: 4000-20000 Hz
            float32 presence         16        0.0 - 1.0: 2000-6000 Hz
            float32 brilliance       20        0.0 - 1.0: 6000-20000 Hz
            float32 centroid         24        0.0 - 1.0: Spectral center of mass
            float32 flux             28        0.0 - 5.0+: Spectral change rate (onset)
            float32 rolloff          32        0.0 - 1.0: 85% energy bandwidth
            float32 spread           36        0.0 - 1.0: Spectral variance
            float32 zcr              40        0.0 - 1.0: Zero-crossing rate
            uint8   beat             44        0 or 1: Beat detected in this frame
            uint8   beat_strength    45        0 - 255: Strength of detected beat
            uint8   bpm_est          46        0 - 240: Estimated BPM (0 if unknown)
            uint8   _pad             47        Alignment
            uint8   bass_level       48        0 - 255: AGC-scaled bass for LEDs
            uint8   mid_level        49        0 - 255: AGC-scaled mid for LEDs
            uint8   treble_level     50        0 - 255: AGC-scaled treble for LEDs
            uint8   energy_level     51        0 - 255: AGC-scaled energy for LEDs
            uint8   presence_level   52        0 - 255: AGC-scaled presence for LEDs
            uint8   centroid_level   53        0 - 255: AGC-scaled centroid for LEDs
            uint8   flux_level       54        0 - 255: AGC-scaled flux for LEDs
            uint8   _pad2            55        Alignment
            """
        except:
            try:
                # Optimized I2S configuration matching working prototype
                SAMPLE_RATE = 31000
                SAMPLES_PER_FRAME = 128
                BITS = 16

                self.i2s = I2S(
                    0,
                    sck=Pin(PIN_I2S_SCK),
                    ws=Pin(PIN_I2S_WS),
                    sd=Pin(PIN_I2S_SD),
                    mode=I2S.RX,
                    bits=BITS,
                    format=I2S.MONO,
                    rate=SAMPLE_RATE,
                    ibuf=4096  # Increased from 1024 (4x larger buffer = smoother operation)
                )
            except OSError as e:
                print("[I2S] Init failed:", e)
                raise
        
    def audio_ready(self):
        return self._fft_mod.ready() if hasattr(self, '_fft_mod') else False

    def clear_audio_ready(self):
        if hasattr(self, '_fft_mod'): self._fft_mod.clear_ready()

    def configure_audio(self, size=256, bands=12, decay=0.92, agc_dec=0.99, beat_thr=0.25, agc_floor=0.001, gate=0.001):
        self._last_audio_cfg = (size, bands, decay, agc_dec, beat_thr, agc_floor, gate)
        if hasattr(self, '_fft_mod'):
            self._fft_mod.configure(size, bands, decay, agc_dec, beat_thr, agc_floor, gate)

    def get_audio_features(self):
        return self.mv_feat

    def get_audio_bands(self):
        return self.mv_bands
        
    def get_audio_magnitudes(self):
        return self.mv_mag

    def set_i2c(self):
        # I2C interface initialization and pin assignment
        self.i2c = SoftI2C(scl=Pin(PIN_I2C_SCL), sda=Pin(PIN_I2C_SDA), freq=1000000, timeout=50000)

    def scan_i2c(self):
        ###scan if adresses are not known
        i2c_scan = self.i2c.scan()
        for name in i2c_scan:
            print('I2C interface adress',hex(name), name)

    def set_bme(self):
        # global bme
        # BME280 sensor initialization
        self.bme = None
        try:
            from lib.bme280 import BME280
            self.bme = BME280(i2c=self.i2c)  # temperature, humidity and pressure sensor
            self.temperature = self.bme.temperature
            self.humidity = self.bme.humidity
            self.pressure = self.bme.pressure
        except:
            self.temperature = 0
            self.humidity = 0
            self.pressure = 0
            return 'BME280 ERROR'

    def set_ds(self):
        # DS3231 & RTC initialization
        self.ds = None
        try:
            from lib.ds3231 import DS3231
            self.ds = DS3231(self.i2c)
            time.sleep(3)
            # datetime get format = (year, month, monthday, weekday, hour, minute, second, 0)
            self.year, self.month, self.day, self.weekday, self.hour, self.minutes, self.seconds, _ = self.ds.datetime()
            self.ds_set = True
        except:
            print('DS3231 initialization error')
            self.set_initial_date_and_time()
            self.ds_set = False


    def set_rtc(self):
        self.rtc = RTC()
        try:
            self.rtc.datetime(self.ds.datetime())  # set the DS3231 time to the RTC time
            # datetime get format = (year, month, monthday, weekday, hour, minute, second, 0)
            self.rtc_set = True
        except:
            self.set_initial_date_and_time()
            self.rtc.datetime(
                (self.year, self.month, self.day, self.day_of_week(self.year, self.month, self.day), 0, 0, 0, 0))
            self.rtc_set_flag = True

    def set_bh1750(self):
        self.bh1750 = None
        try:
            from lib.bh1750 import BH1750
            self.bh1750 = BH1750(self.i2c)
            self.lux = self.bh1750.luminance
            self.smoothed_lux = float(self.lux)

        except:
            print('BH1750 light sensor initialization error')

    @micropython.native
    def process_lux(self, raw_lux, target_brightness=255):
        """
        Przetwarza surowy odczyt I2C na stabilną wartość jasności 0-255,
        skrojoną pod specyfikę diod adresowalnych (eliminacja mrowienia i schodkowania).
        """
        # 1. FILTR DOLNOPRZEPUSTOWY (EMA)
        self.smoothed_lux = (self.lux_alpha * float(raw_lux)) + ((1.0 - self.lux_alpha) * self.smoothed_lux)

        brackets = (1, 7, 12, 26, 51)
        outputs =  (3, 8, 14, 50, 100)
        
        low, high = 0, len(brackets)
        while low < high:
            mid = (low + high) // 2
            if brackets[mid] <= raw_lux:
                low = mid + 1
            else:
                high = mid
                
        mapped_brightness = outputs[low] if low < len(outputs) else target_brightness
    
        final_brightness = min(target_brightness, mapped_brightness)

        # 3. HISTEREZA (Krok min. 3)
        if abs(final_brightness - self.last_brightness) >= 3:
            self.last_brightness = final_brightness

        if self.last_brightness > target_brightness:
            self.last_brightness = target_brightness

        return self.last_brightness


    # Module-level lookup tables (defined once, outside class)
    _IR_KEYS = (0x1FE48B7, 0x1FE58A7, 0x1FE7887, 0x1FEF807, 0x1FE30CF, 0x1FE10EF, 0x1FE906F)
    _IR_VALS = bytearray([1, 2, 3, 4, 5, 10, 11])

    def set_ir(self):
        try:
            import ir_core1
            try:
                ir_core1.stop()
            except:
                pass
            self.ir_core1 = ir_core1
            self.ir_core1.start(PIN_IR_RX)
            self._last_ir_cmd = None
            self._last_ir_time = 0
            self._last_ir_raw = 0
        except Exception as e:
            print(f"IR core1 start error: {e}")
            self.ir_core1 = None
            try:
                from lib.ir_irq import IRReceiver
                self.ir = IRReceiver(pin=PIN_IR_RX)
            except Exception as e2:
                print("IR Receiver initialization failed:", e2)
                self.ir = None

    def get_ir_command(self):
        if self.ir_core1 is None or not self.ir_core1.available():
            return None
        irc = self.ir_core1.read()
        if irc is None:
            return None
            
        import time
        now = time.ticks_ms()
        
        protocol = irc.get('protocol')
        raw = irc.get('raw')
        
        # Debounce / Anti-hold for NEC
        if raw == self._last_ir_raw and time.ticks_diff(now, self._last_ir_time) < 300:
            return None
            
        self._last_ir_raw = raw
        self._last_ir_time = now
        
        # NEC decoding using address and command
        if protocol == 'NEC':
            addr = irc.get('address')
            cmd = irc.get('command')
            if addr == 0x01 or addr == 0x00:
                if cmd == 0x48 or cmd == 0x45: return 1  # CMD_UP
                if cmd == 0x58 or cmd == 0x46: return 2  # CMD_DOWN
                if cmd == 0x78 or cmd == 0x44: return 3  # CMD_LEFT
                if cmd == 0xF8 or cmd == 0x43: return 4  # CMD_RIGHT
                if cmd == 0x30 or cmd == 0x40: return 5  # CMD_CENTER
                if cmd == 0x10 or cmd == 0x07: return 10 # MODE_L2
                if cmd == 0x90 or cmd == 0x15: return 11 # RAND
                
        # Fallback raw mapping (if it matches _IR_KEYS)
        return self.ir_map(raw)

    def ir_map(self, raw):
        for i in range(len(self._IR_KEYS)):
            if self._IR_KEYS[i] == raw:
                return self._IR_VALS[i]
        return 0  # CMD_NONE

    def set_buttons(self):
        from lib.switches import Button, AnalogJoystick
        
        self.b_left = Button(PIN_BUTTON_L, powering='GND')
        self.b_right = Button(PIN_BUTTON_R, powering='GND')
        self.b_minus = Button(PIN_BUTTON_MINUS, powering='GND')
        self.b_plus = Button(PIN_BUTTON_PLUS, powering='GND') 
        self.b_confirm = Button(PIN_BUTTON_C, powering='GND')
        self.b_l1 = Button(PIN_BUTTON_L1, powering='GND')
        self.b_l2 = Button(PIN_BUTTON_L2, powering='GND')

        self.pir = Button(PIN_BUTTON_PIR, powering='PWR')
        wake_on_ext0(PIN_BUTTON_PIR, WAKEUP_ANY_HIGH)

    def has_input(self):
        """Check if any input device has a NEW pending input (edge detected)."""
        if b_refresh():
            return True
        else:
            return False

    def poll_input(self):
        
        # Hardware buttons — b_light / b_set_rtc handled directly by caller via state_value()
        for btn, cmd1, cmd2 in ((self.b_plus, CMD_UP, CMD_UP_L), (self.b_minus, CMD_DOWN, CMD_DOWN_L),
                                (self.b_left, CMD_LEFT, CMD_LEFT_L), (self.b_right, CMD_RIGHT, CMD_RIGHT_L),
                                (self.b_confirm, CMD_CONFIRM, CMD_CONFIRM_L), (self.b_l1, CMD_L1, CMD_L1_L),
                                (self.b_l2, CMD_L2, CMD_L2_L)):
            st = btn.state_value()
            if st < 0:
                btn.state_value(0)
                return cmd2
            elif st>0:
                btn.state_value(0)
                return cmd1
        b_refresh(False)  # Clear refresh state after polling


    def set_buzzer(self):
        self.buzzer = Pin(PIN_BUZZER, Pin.OUT)

    # LED setup methods - FIXED to use new Aleds API
    def set_led1(self, x, y):
        n = x * y
        gc.collect()
        el_leds_buffer = bytearray(n * 3)
        el_leds = AledsRgb(pin=PIN_LED1, buffer=el_leds_buffer, n=n, bpp=3, order=AledsRgb.ORDER_GRB)
        self.led1 = Led(1, el_leds)
        self.led1.cols = 19
        self.led1.rows = 19
        self.led1.length = n
        self.sections = ((0, n - 1),(0, 36),(36, 48),(48, n - 1))
        self.led1.index_table = bytearray.fromhex("ffffffffffffffffff1effffffffffffffffffffffffffffffffff1f2a1dffffffffffffffffffffffffffffff2129ff2b1cffffffffffffffffffffffffff202728ff2c2d1bffffffffffffffffffffff2226ffffffffff2e1affffffffffffffffff2325ffffffffffffff2f19ffffffffffffff0024ffffffffffffffffff3018ffffffffff01ffffffffffffffffffffffffff17ffffff02ffffffffffffffffffffffffffffff16ff03ffffffffffffffffffffffffffffffffff15ff04ffff3bffffffffffffff333231ffff14ffffff053cff3a39ffffffff34ffff47ff13ffffffffff063dffff38373635ff4546ff12ffffffffffffff073e3f40ffffff44ffff11ffffffffffffffffff08ffff414243ffff10ffffffffffffffffffffff09ffffffffff0fffffffffffffffffffffffffff0affffff0effffffffffffffffffffffffffffff0bff0dffffffffffffffffffffffffffffffffff0cffffffffffffffffff")
        self.led1.aled_object.clear()
        self.led1.aled_object.write()
        gc.collect()

    def set_led2(self, x, y):
        n = x * y
        gc.collect()
        tl_leds_buffer = bytearray(n * 3)
        tl_leds = AledsRgb(pin=PIN_LED2, buffer=tl_leds_buffer, n=n, bpp=3, order=AledsRgb.ORDER_RGB)
        self.led2 = Led(2, tl_leds)

        self.led2.cols = x
        self.led2.rows = y
        self.led2.length = self.led2.cols * self.led2.rows
        self.led2.aled_object.clear()
        self.led2.aled_object.write()
        gc.collect()

    def get_led_device(self, id):
        """Get LED device by ID"""
        return (None, self.led1, self.led2)[id]

    def gc_collect(self):
        """Collect garbage"""
        gc.collect()

    def gc_mem_free(self):
        """Free memory"""
        return gc.mem_free()

    def buzzer_sound(self, state='On'):
        """Enable/disable buzzer"""
        if state == 'On':
            self.buzzer_active = True
        elif state == 'Off':
            self.buzzer_active = False
        return

    def beep(self, duration=10):
        """Make beep sound"""
        if self.buzzer_active and hasattr(self, 'buzzer'):
            self.buzzer.on()
            time.sleep_ms(duration)
            self.buzzer.off()

    @micropython.viper
    def get_led_index(self, led_id: int, x: int, y: int) -> int:
        """
        Get physical index for LED1 or LED2.
        led_id: 1 for LED1, 2 for LED2
        """
        cols = 0
        rows = 0

        if led_id == 1:
            cols = int(self.led1.cols)
            rows = int(self.led1.rows)
        else:
            cols = int(self.led2.cols)
            rows = int(self.led2.rows)

        if x < 0 or x >= cols or y < 0 or y >= rows:
            return -1

        # 4. Logika specyficzna dla danego led_id
        if led_id == 1:
            p_table = ptr8(self.led1.index_table)
            idx = int(p_table[y * cols + x])
            if idx == 255:
                return -1
            return idx
        else:
            if x & 1:
                return x * rows + (rows - 1 - y)
            else:
                return x * rows + y

    def go_sleep(self):
        self.led1.aled_object.clear()
        self.led2.aled_object.clear()
        self.led1.aled_object.write()
        self.led2.aled_object.write()
        self._fft_mod.stop()
        self.ir_core1.stop()
        self.clear_pir()

        wake_on_ext0(PIN_BUTTON_PIR, WAKEUP_ANY_HIGH)
        time.sleep_ms(200)
        lightsleep()


        time.sleep_ms(200)
        self.set_i2s()
        self.set_ir()

        print("Wybudzono przez PIR!")
        
        # Immediate Time Restoration from DS3231 to prevent 9-minute time drift
        try:
            if hasattr(self, 'ds') and self.ds:
                dt = self.ds.datetime()
                self.year, self.month, self.day, self.weekday, self.hour, self.minutes, self.seconds = (
                    dt[0], dt[1], dt[2], dt[3], dt[4], dt[5], dt[6]
                )
                if hasattr(self, 'rtc') and self.rtc:
                    self.rtc.datetime((dt[0], dt[1], dt[2], dt[3], dt[4], dt[5], dt[6], 0))
                print("[Sleep] Restored time from DS3231 RTC on wakeup.")
        except Exception as e:
            print("[Sleep] DS3231 read failed, re-initializing I2C & DS3231:", e)
            try:
                self.set_i2c()
                from lib.ds3231 import DS3231
                self.ds = DS3231(self.i2c)
                self.set_bme()
                self.set_bh1750()
                dt = self.ds.datetime()
                self.year, self.month, self.day, self.weekday, self.hour, self.minutes, self.seconds = (
                    dt[0], dt[1], dt[2], dt[3], dt[4], dt[5], dt[6]
                )
                if hasattr(self, 'rtc') and self.rtc:
                    self.rtc.datetime((dt[0], dt[1], dt[2], dt[3], dt[4], dt[5], dt[6], 0))
                print("[Sleep] Reinitialized and restored time from DS3231 RTC.")
            except Exception as e2:
                print("[Sleep] DS3231 recovery failed:", e2)

        self.clear_pir()
        self.sync_on_wakeup()
        return

    def sync_on_wakeup(self):
        """Perform holiday check, reconnect WiFi, and run NTP sync upon waking up."""
        print("[Sleep] Starting wakeup sync...")
        # 1. Update holiday check with the restored RTC time
        try:
            self.holidays(self.year)
            self.is_holiday_today = self.is_holiday(self.day, self.month, self.year)
            self.is_special_today = self.is_special(self.day, self.month, self.year)
            print("[Sleep] Initial holiday check completed:", self.is_holiday_today)
        except Exception as e:
            print("[Sleep] Initial holiday check failed:", e)

        # 2. Connect to WiFi and run NTP sync
        try:

            print("[Sleep] Connecting to WiFi for NTP/weather sync...")
            self.wlan, ip = wifi_manager.connect(self.credentials, self.settings, timeout_ms=5000)
            
            if self.wlan and self.wlan.isconnected():
                self.sync_ntp()
                self.sync_weather()
                # Re-run holiday check in case the year/date changed after NTP synchronization
                self.holidays(self.year)
                self.is_holiday_today = self.is_holiday(self.day, self.month, self.year)
                self.is_special_today = self.is_special(self.day, self.month, self.year)
                print("[Sleep] NTP sync and holiday checking on wakeup successful.")
            else:
                print("[Sleep] WiFi connection failed, skipping NTP sync.")
        except Exception as e:
            print("[Sleep] NTP sync on wakeup failed:", e)

    def clear_pir(self):
        self.pir_time = time.ticks_ms()
        self.pir.clear_button_state()

    def sleepy(self):
        if time.ticks_diff(time.ticks_ms(), self.pir_time) > self.pir_delay:
            if self.pir.state_value() == 0:
                return True
            else:
                return False
        return False

    def get_sensor_data(self):


        try:
            t = self.bme.temperature
            h = self.bme.humidity
            p = self.bme.pressure
            l = self.bh1750.luminance
            if self.temperature != t or self.humidity != h or self.pressure != p or self.lux != l:
                self.temperature = t
                self.humidity = h
                self.pressure = p
                self.lux = l
                self.sensor_refreshed = True
            else:
                self.sensor_refreshed = False
        except Exception:
            # On sensor error, keep last values but mark as not refreshed
            self.sensor_refreshed = False

    # Date and time methods
    def leap_year(self, year):
        """Check if year is leap year"""
        return bool((not year % 4) ^ (not year % 100))

    def get_month_length(self, month,
                         d=None):
        """Get number of days in month"""
        if d is None:
            d = bytearray((31, 0, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31))
        days = d[month - 1]
        return days if days else (29 if self.leap_year(self.year) else 28)

    def day_of_week(self, year, month, day):
        """Calculate day of week (0=Mon, 6=Sun)"""
        t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
        year -= month < 3
        return ((year + year // 4 - year // 100 + year // 400 +
                 t[month - 1] + day) - 1) % 7

    def get_name_of_the_day(self, wday, days=None):
        """Get name of the day"""
        if days is None:
            days = ('PONIEDZIALEK', 'WTOREK', 'SRODA', 'CZWARTEK', 'PIATEK', 'SOBOTA', 'NIEDZIELA')
        return days[wday]

    def set_rtc_time(self, year, month, day, hour, minutes, seconds):
        """Set RTC time"""
        self.year = year
        self.month = month
        self.day = day
        self.hour = hour
        self.minutes = minutes
        self.seconds = seconds
        self.weekday = self.day_of_week(year, month, day)

        time_tuple = (self.year, self.month, self.day, self.weekday,
                      self.hour, self.minutes, self.seconds)
        try:
            if hasattr(self, 'ds'):
                self.ds.datetime(time_tuple)
            if hasattr(self, 'rtc'):
                self.rtc.datetime(self.ds.datetime())
            self.rtc_set_flag = True
        except:
            self.rtc_set_flag = False

    def set_initial_date_and_time(self):
        """Set initial date and time"""
        self.year = 2026
        self.month = 6
        self.day = 1
        self.weekday = self.day_of_week(self.year, self.month, self.day)
        self.hour = 0
        self.minutes = 0
        self.seconds = 0

    def update_time(self):
        """Update time from RTC"""
        if hasattr(self, 'rtc'):
            datetime_now = self.rtc.datetime()
            if self.seconds != datetime_now[6]:
                (self.year, self.month, self.day, self.weekday,
                 self.hour, self.minutes, self.seconds, _) = datetime_now
                self.time_refreshed = True
                if self.hour == 3 and self.minutes == 0 and self.seconds < 3:
                    self.holidays(self.year)  # Generate holiday cache at 3 o'clock every day
                    self.is_holiday_today = self.is_holiday(self.day, self.month, self.year)  # Check if today is holiday
                    self.is_special_today = self.is_special(self.day, self.month, self.year)  # Check if today is special day
            else:
                self.time_refreshed = False

    def get_data(self):
        """Update time and sensor data"""
        self.update_time()
        if hasattr(self, 'get_sensor_data'):
            self.get_sensor_data()
        try:
            micropython.schedule(lambda x: self.check_network_syncs(), None)
        except Exception:
            pass


    def prefix(self, number):
        """Add leading zero if needed"""
        return '0' + str(number) if number < 10 else str(number)

    def check_flags(self):
        if self.time_refreshed or self.sensor_refreshed:
            self.display_refresh = True

    def holidays(self, start_year):
        self.FIXED_HOLIDAYS = {
            (1, 1): "NOWY ROK",
            (1, 6): "TRZECH KROLI",
            (5, 1): "SWIETO PRACY",
            (5, 3): "SWIETO KONSTYTUCJI",
            (8, 15): "WNIEBOWZIECIE NMP",
            (11, 1): "WSZYSTKICH SWIETYCH",
            (11, 11): "SWIETO NIEPODLEGLOSCI",
            (12, 24): "WIGILIA",
            (12, 25): "BOZE NARODZENIE 1.DZIEN",
            (12, 26): "BOZE NARODZENIE 2.DZIEN"
        }

        self.SPECIAL_DAYS = {
            (2, 18): "PATRYK URODZINY",
            (2, 20): "MAGDALENKA URODZINY",
            (3, 8): "DZIEN KOBIET",
            (5, 26): "DZIEN MATKI",
            (6, 1): "DZIEN DZIECKA",
            (6, 17): "ROCZNICA SLUBU",
            (6, 23): "DZIEN OJCA",
            (7, 27): "TOMEK URODZINY",
            (9, 10): "LAURKA URODZINY",
            (9, 30): "DZIEN CHLOPAKA",
            (10, 14): "DZIEN NAUCZYCIELA",
            (12, 6): "MIKOLAJKI",
            (12, 31): "SYLWESTER"
        }

        self.moveable_holidays = {}
        self._generate_moveable_holidays(start_year, 1)

    def _add_days(self, year, month, day, days_to_add):
        t = time.mktime((year, month, day, 0, 0, 0, 0, 0))
        t += days_to_add * 86400
        f = time.localtime(t)
        return f[0], f[1], f[2]

    def _generate_moveable_holidays(self, start_year, years_count):
        self.moveable_holidays = {}
        for year in range(start_year, start_year + years_count):
            a, b, c = year % 19, year // 100, year % 100
            d, e = b // 4, b % 4
            f = (b + 8) // 25
            g = (b - f + 1) // 3
            h = (19 * a + b - d - g + 15) % 30
            i, k = c // 4, c % 4
            l = (32 + 2 * e + 2 * i - h - k) % 7
            m = (a + 11 * h + 22 * l) // 451
            e_m = (h + l - 7 * m + 114) // 31
            e_d = ((h + l - 7 * m + 114) % 31) + 1

            self.moveable_holidays[(year, e_m, e_d)] = "WIELKANOC"

            for days, descr in ((1, "SMIGUS DYNGUS"), (49, "ZIELONE SWIATKI"), (60, "BOZE CIALO")):
                y, m, d = self._add_days(year, e_m, e_d, days)
                self.moveable_holidays[(y, m, d)] = descr

    def is_holiday(self, day, month, year):

        if name := self.FIXED_HOLIDAYS.get((month, day)):
            return True, name

        if name := self.moveable_holidays.get((year, month, day)):
            return True, name

        return False, None

    @micropython.native
    def is_special(self, day, month, year):
        if name := self.SPECIAL_DAYS.get((month, day)):
            return True, name
        return False, None

    def init_wifi_and_sync(self):
        """Initializes WiFi connection and performs startup time and weather synchronization."""
        # Initialize weather attributes with defaults
        self.last_weather_sync = 0
        self.last_ntp_sync = 0
        self.last_sync_attempt = 0
        self.weather_temp = None
        self.weather_feels_like = None
        self.weather_temp_min = None
        self.weather_temp_max = None
        self.weather_humidity = None
        self.weather_pressure = None
        self.weather_wind_speed = None
        self.weather_wind_dir = None
        self.weather_description = None
        self.weather_sunrise = None
        self.weather_sunset = None

        print("[Sync] Loading settings...")
        self.settings = {}
        try:
            import json
            with open("settings.json", "r") as f:
                self.settings = json.load(f)
            print("[Sync] Loaded settings.json successfully.")
        except Exception as e:
            print("[Sync] Failed to load settings.json:", e)
            self.settings = {
                "ntp_server": "pool.ntp.org",
                "latitude": 51.177192,
                "longitude": 17.00103,
                "timezone_offset": 1,
                "dst_enabled": False,
                "ntp_enabled": True,
                "wifi_static_ip_enabled": False,
                "wifi_static_ip": "192.168.101.150",
                "wifi_static_subnet": "255.255.255.0",
                "wifi_static_gateway": "192.168.101.1",
                "wifi_static_dns": "8.8.8.8",
                "status_messages_enabled": True
            }

        try:
            import credentials
            self.credentials = credentials
        except ImportError:
            print("[Sync] credentials.py not found. WiFi/Weather sync disabled.")
            self.credentials = None
            return

        try:
            from lib import wifi_manager
            print("[Sync] Connecting to WiFi (startup)...")
            self.wlan, ip = wifi_manager.connect(self.credentials, self.settings, timeout_ms=15000)
        except Exception as e:
            print("[Sync] WiFi connect failed:", e)
            self.wlan = None

        if self.wlan and self.wlan.isconnected():
            self.last_sync_attempt = time.time()
            self.sync_ntp()
            self.sync_weather()

    def save_settings(self):
        """Persist settings to settings.json."""
        try:
            import json
            with open("settings.json", "w") as f:
                json.dump(self.settings, f)
            print("[Sync] Settings saved successfully.")
            return True
        except Exception as e:
            print("[Sync] Failed to save settings:", e)
            return False

    def sync_ntp(self):
        """Synchronize system time and DS3231 RTC using NTP."""
        if not self.wlan or not self.wlan.isconnected():
            print("[NTP] Cannot sync: WiFi not connected.")
            return False

        try:
            ntp_host = self.settings.get("ntp_server", "pool.ntp.org")
            print("[NTP] Syncing with {}...".format(ntp_host))
            ntptime.host = ntp_host
            ntptime.settime()  # Sets the system RTC to UTC

            utc_sec = time.time()
            tz_offset = self.settings.get("timezone_offset", 1)
            local_sec = utc_sec + int(tz_offset * 3600)
            
            # Check standard local time for DST
            std_tm = time.localtime(local_sec)
            dst_enabled = self.settings.get("dst_enabled", False)
            auto_dst = self.is_dst_active(std_tm[0], std_tm[1], std_tm[2], std_tm[3])
            print("[NTP] tz_offset={}, dst_enabled={}, auto_dst_active={}".format(tz_offset, dst_enabled, auto_dst))
            if dst_enabled or (tz_offset == 1 and auto_dst):
                local_sec += 3600

            local_tm = time.localtime(local_sec)

            # Update controller class time attributes immediately
            self.year, self.month, self.day, self.hour, self.minutes, self.seconds = (
                local_tm[0], local_tm[1], local_tm[2], local_tm[3], local_tm[4], local_tm[5]
            )
            self.weekday = local_tm[6]

            # Set internal system RTC
            if hasattr(self, 'rtc') and self.rtc:
                self.rtc.datetime((local_tm[0], local_tm[1], local_tm[2], local_tm[6], local_tm[3], local_tm[4], local_tm[5], 0))
                print("[NTP] Internal system RTC set successfully using self.rtc.")
            else:
                rtc = RTC()
                rtc.datetime((local_tm[0], local_tm[1], local_tm[2], local_tm[6], local_tm[3], local_tm[4], local_tm[5], 0))
                self.rtc = rtc
                print("[NTP] Internal system RTC set successfully using new RTC instance.")

            # Set external DS3231 RTC
            try:
                if hasattr(self, 'ds') and self.ds:
                    self.ds.datetime((local_tm[0], local_tm[1], local_tm[2], local_tm[6], local_tm[3], local_tm[4], local_tm[5]))
                    print("[NTP] DS3231 RTC set successfully.")
                else:
                    print("[NTP] DS3231 RTC not available to update.")
            except Exception as ds_err:
                print("[NTP] DS3231 RTC sync error:", ds_err)

            self.time_refreshed = True
            self.display_refresh = True
            self.last_ntp_sync = time.time()
            print("[NTP] Synchronization successful. Local Time: {:02d}:{:02d}:{:02d}".format(local_tm[3], local_tm[4], local_tm[5]))
            return True
        except Exception as e:
            print("[NTP] Synchronization failed:", e)
            return False

    def sync_weather(self):
        """Fetch weather data from OpenWeatherMap."""
        if not self.wlan or not self.wlan.isconnected():
            print("[Weather] Cannot sync: WiFi not connected.")
            return False

        if not self.credentials or self.credentials.OPENWEATHER_API_KEY == "Your_OpenWeatherMap_API_Key":
            print("[Weather] Cannot sync: API key not configured.")
            return False

        try:
            import urequests
            lat = self.settings.get("latitude", 51.177192)
            lon = self.settings.get("longitude", 17.00103)
            api_key = self.credentials.OPENWEATHER_API_KEY

            url = "http://api.openweathermap.org/data/2.5/weather?lat={}&lon={}&appid={}&units=metric&lang=pl".format(lat, lon, api_key)
            print("[Weather] Fetching outdoor weather data...")
            res = urequests.get(url)
            if res.status_code == 200:
                data = res.json()
                self.visibility = data["visibility"]
                self.weather_temp = data["main"]["temp"]
                self.weather_feels_like = data["main"]["feels_like"]
                self.weather_humidity = data["main"]["humidity"]
                self.weather_pressure = data["main"]["pressure"]

                self.weather_wind_speed = data["wind"]["speed"]
                self.weather_wind_dir = data["wind"]["deg"]
                self.weather_description = data["weather"][0]["description"]
                self.weather_sunrise = data["sys"]["sunrise"]
                self.weather_sunset = data["sys"]["sunset"]

                self.last_weather_sync = time.time()
                print("[Weather] Data fetched successfully.")
                res.close()
                return True
            else:
                print("[Weather] HTTP status error:", res.status_code)
                res.close()
                return False
        except Exception as e:
            print("[Weather] Failed to fetch weather:", e)
            return False

    def check_network_syncs(self):
        """Check if scheduled syncs are due."""
        now = time.time()
        # Cooldown between any sync attempt (5 minutes)
        if now - self.last_sync_attempt >= 300:
            want_weather = (self.weather_temp is None or (now - self.last_weather_sync >= 1200))
            want_ntp = (self.last_ntp_sync == 0 or (now - self.last_ntp_sync >= 86400))

            if want_weather or want_ntp:
                self.last_sync_attempt = now
                import network
                wlan_sta = network.WLAN(network.STA_IF)
                if not wlan_sta.isconnected():
                    print("[Sync] WiFi disconnected. Attempting reconnect...")
                    try:
                        from lib import wifi_manager
                        self.wlan, ip = wifi_manager.connect(self.credentials, self.settings, timeout_ms=5000)
                    except Exception as e:
                        print("[Sync] WiFi reconnect failed:", e)

                if wlan_sta.isconnected():
                    self.wlan = wlan_sta
                    if want_ntp:
                        self.sync_ntp()
                    if want_weather:
                        self.sync_weather()

    @micropython.native
    def get_polish_wind_direction(self, deg):
        """Map wind direction in degrees to Polish abbreviations."""
        if deg is None:
            return ""
        deg = deg % 360
        if 337.5 <= deg or deg < 22.5:
            return "a"      # North
        elif 22.5 <= deg < 67.5:
            return "b"      # North-East
        elif 67.5 <= deg < 112.5:
            return "c"      # East
        elif 112.5 <= deg < 157.5:
            return "d"      # South-East
        elif 157.5 <= deg < 202.5:
            return "e"      # South
        elif 202.5 <= deg < 247.5:
            return "f"      # South-West
        elif 247.5 <= deg < 292.5:
            return "g"      # West
        else:
            return "h"      # North-West

    @micropython.native
    def strip_polish_diacritics(self, text):
        """Replace Polish diacritic letters with plain ASCII characters."""
        mapping = {
            'ą': 'A', 'Ą': 'A',
            'ć': 'C', 'Ć': 'C',
            'ę': 'E', 'Ę': 'E',
            'ł': 'L', 'Ł': 'L',
            'ń': 'N', 'Ń': 'N',
            'ó': 'O', 'Ó': 'O',
            'ś': 'S', 'Ś': 'S',
            'ź': 'Z', 'Ź': 'Z',
            'ż': 'Z', 'Ż': 'Z'
        }
        res = ""
        for char in text:
            res += mapping.get(char, char)
        return res

    @micropython.native
    def is_dst_active(self, year, month, day, hour):
        """Determine if European Summer Time (DST) is active for a given date/time."""
        if month < 3 or month > 10:
            return False
        if month > 3 and month < 10:
            return True

        w_march = self.day_of_week(year, 3, 31)
        last_sunday_march = 31 - (w_march + 1) % 7
        if month == 3:
            if day > last_sunday_march:
                return True
            if day < last_sunday_march:
                return False
            return hour >= 2

        w_oct = self.day_of_week(year, 10, 31)
        last_sunday_oct = 31 - (w_oct + 1) % 7
        if month == 10:
            if day < last_sunday_oct:
                return True
            if day > last_sunday_oct:
                return False
            return hour < 3

    def convert_unix_to_local(self, unix_timestamp):
        """Convert a Unix timestamp to local time tuple using settings and automatic DST."""
        if unix_timestamp is None:
            return time.localtime()
        mpy_timestamp = unix_timestamp - 946684800
        tz_offset = self.settings.get("timezone_offset", 1)
        local_timestamp = mpy_timestamp + int(tz_offset * 3600)
        
        # Check standard local time for DST
        std_tm = time.localtime(local_timestamp)
        dst_enabled = self.settings.get("dst_enabled", False)
        if dst_enabled or (tz_offset == 1 and self.is_dst_active(std_tm[0], std_tm[1], std_tm[2], std_tm[3])):
            local_timestamp += 3600
            
        return time.localtime(local_timestamp)

    def adjust_rtc_time(self, delta_seconds):
        """Adjust internal system and DS3231 hardware RTC time by delta_seconds."""
        try:
            if hasattr(self, 'rtc') and self.rtc:
                dt = self.rtc.datetime()
                # dt is (year, month, mday, weekday, hour, minute, second, subsecond)
                # mktime expects (year, month, mday, hour, minute, second, weekday, yearday)
                t_tuple = (dt[0], dt[1], dt[2], dt[4], dt[5], dt[6], dt[3], 0)
                sec = time.mktime(t_tuple)
                new_sec = sec + delta_seconds
                new_dt = time.localtime(new_sec)
                
                # Update local attributes
                self.year, self.month, self.day, self.hour, self.minutes, self.seconds = (
                    new_dt[0], new_dt[1], new_dt[2], new_dt[3], new_dt[4], new_dt[5]
                )
                self.weekday = new_dt[6]
                
                # Set system RTC
                self.rtc.datetime((new_dt[0], new_dt[1], new_dt[2], new_dt[6], new_dt[3], new_dt[4], new_dt[5], 0))
                
                # Set external DS3231 RTC
                if hasattr(self, 'ds') and self.ds:
                    try:
                        self.ds.datetime((new_dt[0], new_dt[1], new_dt[2], new_dt[6], new_dt[3], new_dt[4], new_dt[5]))
                    except Exception as rtc_err:
                        print("[Sync] Hardware DS3231 adjust failed:", rtc_err)
                print("[Sync] RTC adjusted by {}s successfully.".format(delta_seconds))
        except Exception as e:
            print("[Sync] Failed to adjust RTC time:", e)


    
