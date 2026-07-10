import random
import time
import array
import gc
import micropython
from math import sin, cos, pi, sqrt, atan2, floor

from helpers import EffectsHelpers

# Precomputed Sine Table (256 entries, -127 to 127)
_SIN_TAB = array.array('b', [int(127 * sin(i * 6.283185 / 256)) for i in range(256)])

def _fast_sin(phase_rad):
    return _SIN_TAB[int(phase_rad * 40.7436) & 0xFF]

def _fast_cos(phase_rad):
    return _fast_sin(phase_rad + 1.570796)

# Constants for LED1 layout
LED1_CIRCLE_CW = [4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,3,2,1,0]
LED1_INNER_ARC_V   = [37,38,39,40,41,42,43,44,45,46,47,48]
LED1_CHORDS_LOW_V  = [49,50,51,52,53,54,55,56,57,58,59,60]
LED1_CHORDS_HIGH_V = [62,63,64,65,66,67,68,69,70,71]
LED1_TREE_ALL_V    = LED1_CHORDS_LOW_V + LED1_CHORDS_HIGH_V


_wfall2 = bytearray(138 * 3 * 3) # Waterfall buffer

# Pre-allocated shape templates for _fx_shapes (avoid per-frame tuple creation)
_SHAPE_SPARK = (
    (0, 0, 255),
    (-1, 0, 210), (1, 0, 210), (0, -1, 210), (0, 1, 210),
    (-1, -1, 160), (-1, 1, 160), (1, -1, 160), (1, 1, 160),
    (-2, 0, 100), (2, 0, 100), (0, -2, 100), (0, 2, 100),
    (-2, -1, 60), (-2, 1, 60), (2, -1, 60), (2, 1, 60),
    (-1, -2, 60), (1, -2, 60), (-1, 2, 60), (1, 2, 60),
)
_SHAPE_STAR = (
    (0, 0, 255),
    (-1, 0, 240), (1, 0, 240), (0, -1, 240), (0, 1, 240),
    (-2, 0, 220), (2, 0, 220), (0, -2, 220), (0, 2, 220),
    (-3, 0, 150), (3, 0, 150), (0, -3, 150), (0, 3, 150),
    (-1, -1, 70), (-1, 1, 70), (1, -1, 70), (1, 1, 70),
)
_SHAPE_DIAMOND = (
    (0, 0, 180),
    (-1, 0, 160), (1, 0, 160), (0, -1, 160), (0, 1, 160),
    (-1, -1, 210), (-1, 1, 210), (1, -1, 210), (1, 1, 210),
    (-2, 0, 255), (2, 0, 255), (0, -2, 255), (0, 2, 255),
    (-2, -1, 200), (-2, 1, 200), (2, -1, 200), (2, 1, 200),
    (-1, -2, 200), (1, -2, 200), (-1, 2, 200), (1, 2, 200),
)
_SHAPE_RING = (
    (0, 0, 50),
    (-1, 0, 80), (1, 0, 80), (0, -1, 80), (0, 1, 80),
    (-1, -1, 110), (-1, 1, 110), (1, -1, 110), (1, 1, 110),
    (-2, 0, 255), (2, 0, 255), (0, -2, 255), (0, 2, 255),
    (-2, -1, 240), (-2, 1, 240), (2, -1, 240), (2, 1, 240),
    (-1, -2, 240), (1, -2, 240), (-1, 2, 240), (1, 2, 240),
    (-2, -2, 170), (-2, 2, 170), (2, -2, 170), (2, 2, 170),
)
_SHAPE_CROSS_X = (
    (0, 0, 255),
    (-1, -1, 230), (-1, 1, 230), (1, -1, 230), (1, 1, 230),
    (-2, -2, 200), (-2, 2, 200), (2, -2, 200), (2, 2, 200),
    (-3, -3, 130), (-3, 3, 130), (3, -3, 130), (3, 3, 130),
    (-1, 0, 60), (1, 0, 60), (0, -1, 60), (0, 1, 60),
)
_SHAPE_COMET = (
    (0, 0, 255), (-1, 0, 200), (1, 0, 200), (-2, 0, 110), (2, 0, 110),
    (0, 1, 215), (-1, 1, 160), (1, 1, 160),
    (0, 2, 160), (-1, 2, 100), (1, 2, 100),
    (0, 3, 100), (-1, 3, 50),  (1, 3, 50),
    (0, 4, 45),
)

class AudioEffects(EffectsHelpers):
    """Audio visualization effects engine - reads directly from Controller audio data."""

    def __init__(self, controller, led_device, rows=138, cols=3,
                 # GLOBAL OPTIONS (apply to all modes)
                 smoothing=0.7,
                 peak_hold_ms = 300,
                 peak_fall_ms = 80,
                 peak_color=None,
                 peak_minimum=10.0,
                 brightness=255,
                 bands=12):
        """
        GLOBAL OPTIONS (apply to all render modes)

        Args:
            brightness: Global brightness (0-255, where 255=100%, 127=~50%, 0=off)
        """
        self.c = controller
        self.led = led_device
        self.led_id = led_device.id
        self.aled = led_device.aled_object
        self.rows = self.led.rows
        self.cols = self.led.cols
        self.n_leds = self.aled.n
        self.bands = bands
        self.brightness = max(0, min(255, int(brightness)))  # 0-255 range (8x precision)
        
        # Geometry caching fields
        self.order = self.aled.order
        self.order0 = self.order[0]
        self.order1 = self.order[1]
        self.order2 = self.order[2]
        self.buffer = self.aled.aled_buffer
        self.noise_threshold = 2.0
        self.smoothing = max(0.0, min(1.0, smoothing))

        # PALETTE
        self.pal_len = self.c.pal_length
        # bands mapped evenly from the Controller palette for vivid saturated colors

        self.spectrum_palette = self.hsv_palette(self.bands)
        # GLOBAL OPTIONS

        self.peak_color = peak_color or self._pal_color(self.pal_len // 6)
        self.peak_minimum = max(0.0, peak_minimum)       
        # --- UNIFIED STATE BUFFERS (Using arrays/bytearrays for speed & memory) ---
        # Fixed size 32 covers up to 24 bands comfortably and avoids fragmentation.
        
        # Positions and intensities (0-255 range)
        self._peak_positions = bytearray(self.bands)
        self._peak_intensity = bytearray(self.bands)
        
        # Timing buffers (ticks_ms unsigned long)
        self._peak_timers = array.array('I', [0] * self.bands)
        self._peak_last_hit = array.array('I', [0] * self.bands)
        
        # Float state buffers (FFT values, smoothing)
        self._prev_raw_val = array.array('f', [0.0] * self.bands)
        self._bar_smooth = array.array('f', [0.0] * self.bands)
        
        # Configuration physics
        self.PEAK_HOLD_MS = peak_hold_ms
        self.PEAK_FALL_MS = peak_fall_ms
        self.BAR_FALL_SPEED = 12.0


        # STATE (smoothing & peak tracking)


        # BUFFER & PHYSICAL MAPPING
        self.phys_rows = self.rows

        # Optimization Cache
        self._dist_map = []
        self._init_dist_map()

        # UNIFIED PRE-ALLOCATED PARTICLE POOLS (lazy init — prevents MemoryError / GC stalls)
        self._sparkles_pool = None
        self._sparkles_count = 0
        self._rain_pool = None
        self._rain_count = 0
        self._sparks_pool = None
        self._sparks_count = 0
        self._grav_pool = None
        self._grav_count = 0
        self._bounce_pool = None
        self._bounce_count = 0
        self._trail_pool = None
        self._trail_count = 0
        self._comets = None
        self._comet_trails = None
        self._comet_trail_len = None
        self._edge_path = None
        self._orbit_pool = None
        self._orbit_count = 0
        self._cascade_pool = None
        self._cascade_count = 0
        self._planet_pool = None
        self._planet_count = 0
        self._blackhole_pool = None
        self._blackhole_count = 0

        # EffectsAnimations / EffectsHelpers state
        self.pal_offset = 0
        self.pal_step = 1
        self.counter = 0
        self.step = 1
        self.direction = 1
        self.last_time = time.ticks_ms()
        self.delay = 25
        self.sections = None
        self.fade_in = False
        self.fade_out = False
        self.intermediate = False
        self.repeats = 0
        self.offset = 0
        self._effect_count = 0
        self._effect_max = 0
        self._effect_fields = []
        self._array_pool = {}
        self._occupied = bytearray(self.n_leds)
        self._fire_heat = None
        self._fire_heat_scaled = None
        self._fire_particles = None  # Lazy init as array.array
        self._fs_data = None         # Fire spark particle data
        self._fire_idx = None        # LED index cache for fire render
        self._fire_frame = 0         # Cool-table frame offset

        # Particle state buffers (storm, magdalenas, fade_effect via EffectsAnimations)
        self._particle_status = bytearray(self.n_leds)
        self._particle_color = bytearray(self.n_leds * self.aled.bpp)
        self._particle_mult = array.array('f', [0.0] * self.n_leds)
        self._particle_int0 = bytearray(self.n_leds)


    def hsv_palette(self, colors_qty=12):
        palette = []
        for i in range(colors_qty):
            h = (i * 242) // colors_qty
            rgb = self._hsv_to_rgb(h, 255, 255)
            color = self.aled.apply_gamma(rgb, self.brightness, self.c.gamma_table)
            palette.append(color)
        return palette
    
    def teardown(self, free_pools=True):
        """Free all particle pools and caches. Call before gc.collect() on effect switch."""
        self._sparkles_count = 0
        self._rain_count = 0
        self._sparks_count = 0
        self._grav_count = 0
        self._bounce_count = 0
        self._trail_count = 0
        self._orbit_count = 0
        self._cascade_count = 0
        self._planet_count = 0
        self._blackhole_count = 0
        if self._comet_trail_len is not None:
            for i in range(len(self._comet_trail_len)):
                self._comet_trail_len[i] = 0
        if hasattr(self, '_radial_count'):
            self._radial_count = 0
        self._effect_count = 0
        for i in range(self.n_leds):
            self._occupied[i] = 0
        
        self._fire_heat = None
        self._fire_heat_scaled = None
        self._fire_particles = None
        self._fs_data = None
        self._fire_idx = None
        self._fire_frame = 0
        self._edge_path = None
        self._shape_lanes_h = None
        self._shape_lanes_v = None
        self._cross_cx = None
        self._orb_ring = None
        self._orb_path_c = None
        self._orb_path_r = None
        if hasattr(self, '_orb_path_idx'): self._orb_path_idx = None
        if hasattr(self, '_orb_wipe_tot'): self._orb_wipe_tot = 0.0

        if free_pools:
            self._sparkles_pool = None
            self._rain_pool = None
            self._sparks_pool = None
            self._grav_pool = None
            self._bounce_pool = None
            self._trail_pool = None
            self._comets = None
            self._comet_trails = None
            self._comet_trail_len = None
            self._orbit_pool = None
            self._cascade_pool = None
            self._planet_pool = None
            self._blackhole_pool = None
            self._fountain_particles = None
            self._fountain_palettes = None

    def reset_effect_state(self):
        """Reset effect state on switch (prevents stale state / leaks)."""
        self.teardown(free_pools=False)
        self.last_time = time.ticks_add(time.ticks_ms(), -20000)
        self.sections = None
        self.fade_in = False
        self.fade_out = False
        self.intermediate = False
        self.counter = 0
        self.repeats = 0
        self._active_envelope = 0.0
        
    def _ensure_pool(self, name, size, template):
        pool = getattr(self, name, None)
        if pool is None:
            pool = [list(template) for _ in range(size)]
            setattr(self, name, pool)
        return pool

    def _ensure_sparkles_pool(self):
        return self._ensure_pool('_sparkles_pool', 80, [0, (0, 0, 0), 0.0])

    def _ensure_rain_pool(self):
        return self._ensure_pool('_rain_pool', 50, [0, 0.0, 0.0, 0.0, (0, 0, 0)])

    def _ensure_sparks_pool(self):
        return self._ensure_pool('_sparks_pool', 20, [0.0, 0, 0.0, 0.0])

    def _ensure_grav_pool(self):
        return self._ensure_pool('_grav_pool', 42, [0.0, 0.0, 0.0, 0.0, 0.0, 0])

    def _ensure_bounce_pool(self):
        return self._ensure_pool('_bounce_pool', 15, [0.0, 0.0, 0.0, 0.0, 0, 0.0, 0])

    def _ensure_trail_pool(self):
        return self._ensure_pool('_trail_pool', 16, [0, 0, 0.0])

    def _ensure_comets_pool(self):
        if self._comets is None:
            self._comets = []
            for col in range(self.cols):
                self._comets.append([self.rows * 0.5, 2.5, self.rows * 0.5, int(col * 4) % 12])
            self._comet_trails = [[[0, 0.0] for _ in range(8)] for _ in range(self.cols)]
            self._comet_trail_len = [0] * self.cols
        return self._comets

    def _ensure_orbit_pool(self):
        return self._ensure_pool('_orbit_pool', 60, [0.0, 0.0, 0.0, 0.0, 0.0, 0])

    def _ensure_cascade_pool(self):
        return self._ensure_pool('_cascade_pool', 50, [0.0, 0.0, 0.0, 0.0, 0.0, 0])

    def _ensure_planet_pool(self):
        return self._ensure_pool('_planet_pool', 40, [0.0, 0.0, 0.0, 0.0, 0.0, 0])

    def _ensure_blackhole_pool(self):
        return self._ensure_pool('_blackhole_pool', 80, [0.0, 0.0, 0.0, 0.0, 0.0, 0])

    def _check_active(self, clear=True):
        """Return True if audio energy exceeds threshold, else clear and return None."""
        if clear:
            self.aled.clear()
        if not hasattr(self, '_active_envelope'):
            self._active_envelope = 0.0
        energy = 0.0
        if hasattr(self.c, 'mv_feat') and len(self.c.mv_feat) > 51:
            energy = float(self.c.mv_feat[51])
        if energy >= self.noise_threshold:
            self._active_envelope = 1.0
        else:
            self._active_envelope *= 0.95
        if self._active_envelope > 0.02:
            return True
        return None



    def _warm_color(self, intensity):
        """Fire-like warm color from palette (red-orange-yellow range)."""
        if self.pal_len > 0:
            idx = int((1.0 - max(0.0, min(1.0, intensity))) * 20)
            return self._pal_color(idx)
        return (200, 15, 0)

    def _cool_color(self, intensity):
        """Ice-like cool color from palette (cyan-blue range)."""
        if self.pal_len > 0:
            idx = 85 + int((1.0 - max(0.0, min(1.0, intensity))) * 35)
            return self._pal_color(idx)
        return (0, 100, 200)

    def _init_dist_map(self):
        """Pre-calculate distance/angle maps and index lookup for heavy renderers."""
        self._dist_map = [0.0] * self.n_leds
        self._tunnel_dist = [0.0] * self.n_leds
        self._rift_r = [0.0] * self.n_leds
        self._rift_a = [0.0] * self.n_leds
        self._idx_map = [-1] * (self.rows * self.cols)
        cx = self.cols / 2.0
        cy = self.rows / 2.0

        for row in range(self.rows):
            dy_raw = row - cy
            for col in range(self.cols):
                dx_raw = col - cx
                dist_raw = sqrt(dx_raw*dx_raw + dy_raw*dy_raw)

                # Tunnel scaled distance
                dx_t = dx_raw * 0.5
                dy_t = dy_raw * 0.1
                dist_t = sqrt(dx_t*dx_t + dy_t*dy_t)

                # Rift normalized coords (fixed center approximation for speed)
                dx_r = dx_raw / self.cols
                dy_r = dy_raw / self.rows
                r_r = sqrt(dx_r*dx_r + dy_r*dy_r)
                a_r = atan2(dy_r, dx_r)

                idx = self._physical_index(col, row)
                map_idx = row * self.cols + col
                if 0 <= idx < self.n_leds:
                    self._dist_map[idx] = dist_raw
                    self._tunnel_dist[idx] = dist_t
                    self._rift_r[idx] = r_r
                    self._rift_a[idx] = a_r
                    self._idx_map[map_idx] = idx

    def _physical_index(self, a, b, c=None):
        """Unified indexing supporting both (x, y) and (led_id, x, y) calls."""
        if c is not None:
            led_id = a
            x = b
            y = c
        else:
            led_id = self.led_id
            x = a
            y = b

        return self.c.get_led_index(led_id, x, y)

    def _calc_brightness(self, color,  local_brightness=255):

        lb = local_brightness
        if lb <= 0:
            return (0, 0, 0)
        if lb > 255:
            lb = 255

        gb = self.brightness
        if gb <= 0:
            return (0, 0, 0)
        if gb > 255:
            gb = 255

        r, g, b = color
        # Full brightness fast path — no multiply needed.
        if gb == 255 and lb == 255:
            return r, g, b
        else:
            # 8-bit x 8-bit -> 8-bit scale
            br = (gb * lb) >> 8
            return self.aled.change_brightness(color, br)

    def _set_led(self, idx, color, local_brightness=255):
        """Set LED by physical index with current global brightness."""
        self.aled[idx] = self._calc_brightness(color, local_brightness)

    _set_pixel = _set_led

    def _update_peak(self, band_idx, current_bar_height, now=None):
        if now is None: now = time.ticks_ms()
        
        old_peak = self._peak_positions[band_idx]
        
        if current_bar_height >= old_peak:
            self._peak_positions[band_idx] = current_bar_height
            self._peak_timers[band_idx] = time.ticks_add(now, self.PEAK_HOLD_MS)
            self._peak_last_hit[band_idx] = now
        
        else:
            if time.ticks_diff(self._peak_timers[band_idx], now) <= 0:
                if old_peak > 0:
                    self._peak_positions[band_idx] = old_peak - 1
                self._peak_timers[band_idx] = time.ticks_add(now, self.PEAK_FALL_MS)
                
        return self._peak_positions[band_idx]



    def _ghosting_or_clear(self, enable_ghosting, ghosting_factor):
        """Apply ghosting trail or clear buffer."""
        if enable_ghosting:
            self.aled.apply_brightness_to_buffer(int(ghosting_factor * 255))
        else:
            self.aled.clear()

    def _smooth_bar(self, band_idx, raw_target):
        """Smoothed bar rise/fall. Returns smoothed value."""
        curr_s = self._bar_smooth[band_idx]
        if raw_target > curr_s:
            curr_s = raw_target
        else:
            curr_s = max(0.0, curr_s - self.BAR_FALL_SPEED)
        self._bar_smooth[band_idx] = curr_s
        return curr_s

    def _update_peak_flash(self, band_idx, raw, h, max_height, gb):
        """Update peak flash intensity and return colored peak. White->Red transition."""
        diff = raw - self._prev_raw_val[band_idx]
        self._prev_raw_val[band_idx] = raw
        intensity = int(self._peak_intensity[band_idx])
        if diff > 35 or (h >= max_height and h > 0):
            intensity = 255
        else:
            intensity = max(0, intensity - 12)
        self._peak_intensity[band_idx] = intensity
        p_color = self.get_dynamic_peak_color(band_idx, intensity)
        if gb != 255:
            p_color = self.aled.change_brightness(p_color, gb)
        return p_color

    def _apply_peak_fade(self, p_color, band_idx, now, fade_factor):
        """Fade peak color after hold time. Returns dimmed color."""
        time_passed = time.ticks_diff(now, self._peak_last_hit[band_idx])
        if time_passed > self.PEAK_HOLD_MS:
            fade = 1000000 - ((time_passed - self.PEAK_HOLD_MS) * fade_factor)
            if fade < 50000:
                fade = 50000
            if fade < 1000000:
                p_color = ((p_color[0] * fade) // 1000000,
                           (p_color[1] * fade) // 1000000,
                           (p_color[2] * fade) // 1000000)
        return p_color

    def get_dynamic_peak_color(self, band_idx, intensity):
        """Płynne przejście koloru: intensity 255 = Biały, 0 = Czerwony"""
        # Przy intensity=0 mamy (255, 0, 0) -> Czerwony
        return (255, int(intensity), int(intensity))


    def set_brightness(self, value):
        """Set global brightness 0-255 (255=full, 0=off)."""
        self.brightness = max(0, min(255, int(value)))

    # ── EffectsAnimations / EffectsHelpers adapter API ──────────────────────

    @property
    def segment_length(self):
        return self.n_leds

    @property
    def pal_length(self):
        return self.pal_len

    @property
    def palette(self):
        return self.c.palette

    @property
    def aled_object(self):
        return self.aled

    @property
    def controller(self):
        return self.c

    def update(self):
        pass  # write is handled by the main loop

    def _set_pixel_rc(self, row, col, color, rows=None, cols=None):
        idx = self._physical_index(col, row)
        if 0 <= idx < self.n_leds:
            self._set_led(idx, color)

    def clear_sequence(self, color=(0, 0, 0)):
        if color[0] == 0 and color[1] == 0 and color[2] == 0:
            self.aled.clear()
        else:
            self.aled.set_all(color, self.brightness)

    def clear_particles(self):
        self._effect_count = 0
        n = self.n_leds
        self._occupied[:] = b'\x00' * n
        self._particle_status[:] = b'\x00' * n
        self._particle_color[:] = b'\x00' * (n * self.aled.bpp)
        self._particle_int0[:] = b'\x00' * n
        pm = self._particle_mult
        for i in range(n):
            pm[i] = 0.0
        if hasattr(self, '_fountain_particles') and self._fountain_particles is not None:
            for i in range(len(self._fountain_particles)):
                self._fountain_particles[i] = 0.0

    def direction_change(self):
        self.direction *= -1

    def set_speed(self, speed):
        self.delay = max(1, 1000 // max(1, speed))

    def set_direction(self, direction):
        self.direction = direction

    def _prepare_effect_arrays(self, max_count, **specs):
        same_fields = True
        if not hasattr(self, '_effect_fields') or len(self._effect_fields) != len(specs):
            same_fields = False
        else:
            for name in specs.keys():
                if name not in self._effect_fields:
                    same_fields = False
                    break
        
        if same_fields and hasattr(self, '_effect_max') and self._effect_max >= max_count:
            return
            
        self._effect_count = 0
        self._effect_max = max_count
        self._effect_fields = list(specs.keys())
        for name, typecode in specs.items():
            key = (name, typecode)
            existing = self._array_pool.get(key)
            if existing is None or len(existing) < max_count:
                self._array_pool[key] = array.array(typecode, [0] * max_count)
            setattr(self, '_arr_' + name, self._array_pool[key])
        
        for i in range(self.n_leds):
            self._occupied[i] = 0

    def _effect_swap_remove(self, idx):
        last = self._effect_count - 1
        if idx != last:
            self._arr_led[idx] = self._arr_led[last]
            for name in self._effect_fields:
                arr = getattr(self, '_arr_' + name)
                arr[idx] = arr[last]
        self._effect_count -= 1

    def render_center_split(self, max_height=36, center_offset=-7, show_peaks=True,
                               enable_ghosting=True, ghosting_factor=0.7,
                               enable_peak_flash=True):
        """Modified render_center_split with ghosting and peak flash."""
        is_active = self.c.mv_feat[51]

        bands = self.c.mv_bands
        rows = self.rows
        cols = self.cols
        gb = self.brightness
        now = time.ticks_ms()
        
        self._ghosting_or_clear(enable_ghosting, ghosting_factor)

        center_row = rows // 2 + center_offset
        fade_factor = int((1.0 - ghosting_factor) * 10000)

        spectrum_palette = self.spectrum_palette
        sp_len = len(spectrum_palette)

        for x in range(cols):
            for mode in range(3):
                if mode == 0:
                    band_idx = x
                    color = spectrum_palette[band_idx % sp_len]
                elif mode == 1:
                    band_idx = x + 3
                    color = spectrum_palette[(band_idx + 1) % sp_len]
                else:
                    band_idx = x + 6
                    color = spectrum_palette[(band_idx + 2) % sp_len]
                
                if band_idx >= len(bands) or band_idx >= self.bands: continue
                
                raw = self._smooth_bar(band_idx, float(bands[band_idx]) if is_active else 0.0)
                h = max(0, min(max_height, int((raw / 255.0) * max_height)))
                peak_pos = self._update_peak(band_idx, h, now)
                
                if gb != 255: color = self.aled.change_brightness(color, gb)
                
                p_color = self.peak_color
                if enable_peak_flash:
                    p_color = self._update_peak_flash(band_idx, raw, h, max_height, gb)
                    p_color = self._apply_peak_fade(p_color, band_idx, now, fade_factor)
                
                # Rendering
                if mode == 0: # Down (from center)
                    if h > 0:
                        for r in range(h):
                            y = center_row - 1 - r
                            if 0 <= y < rows:
                                idx = self._physical_index(x, y)
                                if idx >= 0: self.aled[idx] = color
                    if show_peaks and peak_pos > 0:
                        y = center_row - 1 - peak_pos
                        if 0 <= y < rows:
                            idx = self._physical_index(x, y)
                            if idx >= 0: self.aled[idx] = p_color
                elif mode == 1: # Up (from center)
                    if h > 0:
                        for r in range(h):
                            y = center_row + r
                            if 0 <= y < rows:
                                idx = self._physical_index(x, y)
                                if idx >= 0: self.aled[idx] = color
                    if show_peaks and peak_pos > 0:
                        y = center_row + peak_pos
                        if 0 <= y < rows:
                            idx = self._physical_index(x, y)
                            if idx >= 0: self.aled[idx] = p_color
                else: # Upper (from top)

                    if h > 0:
                        for r in range(h):
                            y = rows - 1 - r
                            if 0 <= y < rows:
                                idx = self._physical_index(x, y)
                                if idx >= 0: self.aled[idx] = color
                    if show_peaks and peak_pos > 0:
                        y = rows - 1 - peak_pos
                        if 0 <= y < rows:
                            idx = self._physical_index(x, y)
                            if idx >= 0: self.aled[idx] = p_color

    def render_bars(self, orientation='v', bar_size=8, spacing=2, start_row=18,
                    visible_bands=None, reverse_bands=True, direction='auto', show_peaks=False,
                    enable_ghosting=True, ghosting_factor=0.7,
                    enable_symmetric=False, enable_peak_flash=True, peak_flash_threshold=5, center_offset=-10):
        """Unified rendering for bars. Optimized version with cinematic ghosting and peak transitions."""

        is_active = self.c.mv_feat[51]

        bands = self.c.mv_bands
        n_leds = self.n_leds
        rows = self.rows
        cols = self.cols
        gb = self.brightness
        
        now = time.ticks_ms()

        if visible_bands is None:
            band_indices = list(range(self.bands))
        else:
            band_indices = [i for i, v in enumerate(visible_bands) if v]

        if reverse_bands:
            band_indices = list(reversed(band_indices))

        if direction == 'auto':
            direction = 'up' if orientation == 'v' else 'left'

        mid_row = rows // 2 + center_offset
        current_pos = start_row

        self._ghosting_or_clear(enable_ghosting, ghosting_factor)

        fade_factor = int((1.0 - ghosting_factor) * 10000)

        spectrum_palette = self.spectrum_palette
        sp_len = len(spectrum_palette)

        for display_slot, band_idx in enumerate(band_indices):
            if band_idx >= len(bands) or band_idx >= self.bands: break

            raw_val = self._smooth_bar(band_idx, float(bands[band_idx]) if is_active else 0.0)
            norm = self._norm(raw_val)

            # Base color scaled by global brightness
            base_color = spectrum_palette[band_idx % sp_len]
            if gb != 255:
                color = self.aled.change_brightness(base_color, gb)
            else:
                color = base_color

            # VERTICAL MODE
            if orientation == 'v':
                h_float = norm * bar_size
                h_full = int(h_float)
                h_frac = h_float - h_full

                peak_pos = self._update_peak(band_idx, h_full, now)
                p_color = self._update_peak_flash(band_idx, raw_val, h_full, bar_size, gb)

                row_start = current_pos
                row_end = min(rows, row_start + bar_size)

                if direction == 'up':
                    for r in range(h_full):
                        y = row_start + r
                        if row_start <= y < row_end:
                            for x in range(cols):
                                idx = self._physical_index(x, y)
                                if idx >= 0: self.aled[idx] = color

                    if h_frac > 0.02 and h_full < bar_size:
                        y = row_start + h_full
                        if row_start <= y < row_end:
                            frac_color = self.aled.change_brightness(color, int(h_frac * 255))
                            for x in range(cols):
                                idx = self._physical_index(x, y)
                                if idx >= 0: self.aled[idx] = frac_color

                    if show_peaks and peak_pos > 0 and peak_pos < bar_size:
                        p_color = self._apply_peak_fade(p_color, band_idx, now, fade_factor)
                        y = row_start + peak_pos
                        if row_start <= y < row_end:
                            for x in range(cols):
                                idx = self._physical_index(x, y)
                                if idx >= 0: self.aled[idx] = p_color

                else:
                    y_base = row_start + bar_size - 1
                    for r in range(h_full):
                        y = y_base - r
                        if row_start <= y < row_end:
                            for x in range(cols):
                                idx = self._physical_index(x, y)
                                if idx >= 0: self.aled[idx] = color

                    if h_frac > 0.02 and h_full < bar_size:
                        y = y_base - h_full
                        if row_start <= y < row_end:
                            frac_color = self.aled.change_brightness(color, int(h_frac * 255))
                            for x in range(cols):
                                idx = self._physical_index(x, y)
                                if idx >= 0: self.aled[idx] = frac_color

                    if show_peaks and peak_pos > 0 and peak_pos < bar_size:
                        p_color = self._apply_peak_fade(p_color, band_idx, now, fade_factor)
                        y = y_base - peak_pos
                        if row_start <= y < row_end:
                            for x in range(cols):
                                idx = self._physical_index(x, y)
                                if idx >= 0: self.aled[idx] = p_color

                current_pos += bar_size + spacing

            # HORIZONTAL MODE
            elif orientation == 'h':

                if direction == 'left':
                    cols_range = range(cols)
                else:
                    cols_range = range(cols - 1, -1, -1)

                if enable_symmetric:
                    half_spacing = max(1, spacing // 2)
                    offset = (display_slot // 2) * (bar_size + spacing) + half_spacing
                    if display_slot % 2 == 0:
                        row_start = mid_row + offset
                    else:
                        row_start = mid_row - offset - bar_size
                else:
                    row_start = current_pos

                row_end = min(rows, row_start + bar_size)
                rows_minus_1 = rows - 1
                inv_cols = 1.0 / cols

                for col_idx, x in enumerate(cols_range):
                    r_min = col_idx * inv_cols
                    r_max = (col_idx + 1) * inv_cols

                    b = 0.0
                    if norm >= r_max:
                        b = 1.0
                    elif norm > r_min:
                        b = (norm - r_min) * cols # Simplified (norm-r_min)/(1/cols)

                    if enable_ghosting and b < 1.0:
                        b = b * ghosting_factor

                    if b > 0.01 and 0 <= row_start < rows:
                        # Pre-calculate dimmed color
                        dim_color = self.aled.change_brightness(color, int(b * 255))
                        for y in range(row_start, row_end):
                            idx = self._physical_index(x, y)
                            if idx >= 0: self.aled[idx] = dim_color

                if not enable_symmetric:
                    current_pos += bar_size + spacing

    def render_classic(self, direction='bottom-up', max_height=None, start_row=None, show_peaks=True, 
                       enable_ghosting=True, ghosting_factor=0.7, enable_peak_flash=True, peak_flash_threshold=180, gain=1.0):
        """Classic 3-bar visualization"""
        is_active = self.c.mv_feat[51]

        now = time.ticks_ms()
        gb = self.brightness
        fade_factor = int((1.0 - ghosting_factor) * 10000)

        self._ghosting_or_clear(enable_ghosting, ghosting_factor)

        rows = self.rows
        cols = self.cols
        if max_height is None:
            max_height = rows
        if start_row is None:
            start_row = 0
        spectrum_palette = self.spectrum_palette
        sp_len = len(spectrum_palette)
        bands = self.c.mv_bands
        num_bands = len(bands)

        for x in range(cols):
            band_idx = (x * self.bands) // cols if cols > 0 else 0
            if band_idx >= self.bands:
                band_idx = self.bands - 1
            if band_idx < 0:
                band_idx = 0

            # Safe index for reading from FFT bands memoryview
            fft_band_idx = band_idx
            if fft_band_idx >= num_bands:
                fft_band_idx = num_bands - 1 if num_bands > 0 else 0

            raw_target = float(bands[fft_band_idx]) * gain if (is_active and num_bands > 0) else 0.0

            # Smoothing (using helper)
            curr_s = self._smooth_bar(band_idx, raw_target)
            raw = curr_s
            norm = min(1.0, raw / 255.0)

            h = int(norm * max_height)
            peak_pos = self._update_peak(band_idx, h, now)

            c_idx = x * self.bands // cols
            color = spectrum_palette[c_idx % sp_len]
            if gb != 255: color = self.aled.change_brightness(color, gb)
            
            # Peak Color & Flash Logic (using helpers)
            p_color = self.peak_color
            if enable_peak_flash:
                p_color = self._update_peak_flash(band_idx, raw, h, max_height, gb)
                p_color = self._apply_peak_fade(p_color, band_idx, now, fade_factor)
            
            if direction == 'top-down':
                for r in range(h):
                    y = self.rows - 1 - start_row - r
                    if 0 <= y < self.rows:
                        idx = self._physical_index(x, y)
                        if idx >= 0: self.aled[idx] = color
                if show_peaks and peak_pos > 0:
                    y = self.rows - 1 - start_row - peak_pos
                    if 0 <= y < self.rows:
                        idx = self._physical_index(x, y)
                        if idx >= 0: self.aled[idx] = p_color
            else: # bottom-up
                for r in range(h):
                    y = start_row + r
                    if 0 <= y < self.rows:
                        idx = self._physical_index(x, y)
                        if idx >= 0: self.aled[idx] = color
                if show_peaks and peak_pos > 0:
                    y = start_row + peak_pos
                    if 0 <= y < self.rows:
                        idx = self._physical_index(x, y)
                        if idx >= 0: self.aled[idx] = p_color

    def render_analog_clock(self, show_marks=True, h_width=1.2, m_width=1.0, s_width=0.8, target_brightness=255,
                            auto_brightness=True):
        """
        Analog clock for addressable LEDs. Centered 12 o'clock between LEDs 11 and 12.
        """
        if auto_brightness:
            target_brightness = max(6, self.c.process_lux(self.c.lux))

        h, m, s = self.c.hour, self.c.minutes, self.c.seconds
        total_seconds = s
        total_minutes = m + (total_seconds / 60.0)
        total_hours = (h % 12) + (total_minutes / 60.0)

        # 3. Centrowanie godziny 12
        LED_OFFSET = 12
        h_pos = (total_hours * 3.0 + LED_OFFSET) % 36
        m_pos = (total_minutes * 0.6 + LED_OFFSET) % 36
        s_pos = (total_seconds * 0.6 + LED_OFFSET) % 36

        led_buffer = [[0, 0, 0] for _ in range(36)]

        if show_marks:
            for i in range(12):
                idx = int(floor((i * 3 + LED_OFFSET) % 36))
                led_buffer[idx] = [96 ,96, 96]

        def _apply_sweeping_light(buffer, exact_pos, color_rgb, width):
            base_idx = int(floor(exact_pos))

            for offset in range(-2, 3):
                idx = (base_idx + offset) % 36
                distance = abs(idx - exact_pos)
                if distance > 18:
                    distance = 36 - distance

                if distance < width:
                    factor = 1.0 - (distance / width)

                    r = min(255, buffer[idx][0] + int(color_rgb[0] * factor))
                    g = min(255, buffer[idx][1] + int(color_rgb[1] * factor))
                    b = min(255, buffer[idx][2] + int(color_rgb[2] * factor))
                    buffer[idx] = [r, g, b]

        _apply_sweeping_light(led_buffer, h_pos, (255, 0, 0), width=h_width)  # Godzina
        _apply_sweeping_light(led_buffer, m_pos, (0, 255, 0), width=m_width)  # Minuta
        _apply_sweeping_light(led_buffer, s_pos, (0, 0, 255), width=s_width)  # Sekunda

        self.aled.clear()
        for physical_idx, raw_color in enumerate(led_buffer):
            self._set_led(physical_idx, tuple(raw_color), target_brightness)

    def render_sparkles(self, sparkle_count=3, enable_ghosting=True, ghosting_factor=0.7):
        """Przykładowy efekt generujący losowe iskry nakładane na smugę czasu"""
        if not self._check_active(clear=False):
            self._ghosting_or_clear(enable_ghosting, ghosting_factor)
            return
        pal = self.c.palette
        self._ghosting_or_clear(enable_ghosting, ghosting_factor)

        for _ in range(sparkle_count):
            random_led = random.getrandbits(9) % self.n_leds
            
            random_factor = random.getrandbits(9) % self.pal_len
            random_color = self._pal_color(random_factor)
            
            self.aled[random_led] = random_color

    def render_spiral_audio(self, rotation_speed=3.0, arms=3, enable_ghosting=True, ghosting_factor=0.6):
        """Classic Polar Spiral - Optimized with sharp separation"""

        if not self._check_active(clear=False):
            self._ghosting_or_clear(enable_ghosting, ghosting_factor)
            return
        is_active = self.c.mv_feat[51]
        bands = self.c.mv_bands
        t = time.ticks_ms() / 1000.0

        # 1. Clear or Ghosting (Crucial for separation!)
        self._ghosting_or_clear(enable_ghosting, ghosting_factor)

        rows = self.rows
        cols = self.cols
        center_row = rows / 2.0
        center_col = cols / 2.0
        max_dist = sqrt(center_row*center_row + center_col*center_col)

        n_bands = self.bands
        spectrum_palette = self.spectrum_palette
        sp_len = len(spectrum_palette)

        for row in range(rows):
            dy = float(row) - center_row
            dy2 = dy * dy

            for col in range(cols):
                dx = float(col) - center_col
                dist = sqrt(dx*dx + dy2)

                if dist < 1.0:
                    continue

                dist_norm = dist / max_dist
                band_idx = int(dist_norm * (n_bands - 1))
                if band_idx >= n_bands: band_idx = n_bands - 1
                if band_idx >= len(bands): band_idx = len(bands) - 1
                if band_idx < 0: continue

                raw_amp = float(bands[band_idx]) if is_active else 0.0
                if raw_amp <= 5: continue

                audio_amp = raw_amp / 255.0
                angle = atan2(dy, dx)

                # Spiral formula
                spiral_angle = (3.0 + audio_amp * 2.0) * dist * 0.15 + t * rotation_speed
                angle_diff = abs(sin(spiral_angle - angle * arms))

                # TIGHTER THRESHOLD (0.22) for better separation
                if angle_diff < 0.22:
                    # SQUARED falloff for sharper, crisper edges
                    factor = (1.0 - angle_diff / 0.22)
                    brightness = audio_amp * (factor * factor) * (1.0 - dist_norm * 0.3)
                    color = spectrum_palette[band_idx % sp_len]

                    idx = self._physical_index(col, row)
                    if idx >= 0:
                        self._set_led(idx, color, int(brightness * 255))



    def render_2d_fx(self, mode='auto', vertical=True, horizontal=False, direction=1,
                      ghosting=0.7, color='auto', random_values=False, angle=0.0,
                      speed=1.0, audio_reactive=True, shape_type='circle', **kwargs):
        now = time.ticks_ms()
        t = (now / 1000.0) * speed
        bands = self.c.mv_bands
        num_bands = len(bands)

        if mode == 'colored_snake':
            self.colored_snake(
                num_snakes=kwargs.get('num_snakes', 3),
                colors=kwargs.get('colors', 'R'),
                bg_color=kwargs.get('bg_color', (0, 0, 0)),
                min_len=kwargs.get('min_len', 5),
                max_len=kwargs.get('max_len', 30),
                delay=kwargs.get('delay', 30),
                directions=kwargs.get('directions', None),
            )
            return

        if mode == 'orbital_dots':
            self.render_orbital_dots(
                n_dots=kwargs.get('n_dots', 4),
                ring=kwargs.get('ring', 0),
                direction=direction,
                speed=speed,
                colors=color,
                mode=kwargs.get('dot_mode', 'dots'),
                ghosting=ghosting,
                trail=kwargs.get('trail', 4),
                audio_reactive=audio_reactive,
                pulse=kwargs.get('pulse', True),
            )
            return

        if mode == 'attractor':
            self.render_particle_attractor(
                mass=kwargs.get('mass', 100),
                particles=kwargs.get('particles', 82),
                size=kwargs.get('size', 1),
                friction=int(kwargs.get('friction', 0)),
                color_by_age=bool(kwargs.get('color_by_age', False)),
                move_attractor=bool(kwargs.get('move_attractor', False)),
                swallow=bool(kwargs.get('swallow', False)),
                ghosting=ghosting,
            )
            return

        if mode == 'dna':
            self.render_dna_spiral(
                scroll_speed=kwargs.get('scroll_speed', 8.0),
                cycles=int(kwargs.get('cycles', 3)),
                rung_spacing=int(kwargs.get('rung_spacing', 0)),
                enable_ghosting=(ghosting > 0),
                ghosting_factor=ghosting if ghosting > 0 else 0.72,
                audio_reactive=audio_reactive,
            )
            return

        if mode == 'fire':
            self.render_ps_fire(
                cooling=int(kwargs.get('cooling', 55)),
                sparking=int(kwargs.get('sparking', 120)),
                audio_reactive=audio_reactive,
                speed=float(kwargs.get('speed', 2.0)),
            )
            return

        if mode == 'fireworks':
            self.render_fireworks(
                sparks_per_burst=int(kwargs.get('sparks_per_burst', 14)),
                gravity=int(kwargs.get('gravity', 3)),
                min_interval=int(kwargs.get('min_interval', 400)),
                audio_reactive=audio_reactive,
            )
            return

        self._ghosting_or_clear(ghosting > 0, ghosting)

        if mode == 'scan':
            self._fx_scan(t, direction, audio_reactive, color, vertical, horizontal, bands, num_bands)
        elif mode == 'diagonal':
            self._fx_diagonal(t, direction, audio_reactive, color, angle, bands, num_bands)
        elif mode == 'plasma':
            self._fx_plasma(t, audio_reactive, bands, num_bands)
        elif mode == 'wave':
            self._fx_wave(t, audio_reactive, color, horizontal, bands, num_bands)
        elif mode == 'shapes':
            self._fx_shapes(t, direction, audio_reactive, color, shape_type, bands, num_bands,
                            kwargs.get('move', 'h'), kwargs.get('sine_amp', 0))
        elif mode == 'radial':
            self._fx_radial(t, direction, audio_reactive, bands, num_bands)
        elif mode == 'spiral':
            self._fx_spiral(t, direction, audio_reactive, bands, num_bands)
        elif mode == 'radar':
            self._fx_radar(t, direction)
        elif mode == 'noise':
            self._fx_noise(audio_reactive, bands, num_bands)
        elif mode == 'rain_v':
            self._fx_rain_v(t, direction, audio_reactive, bands, num_bands)
        elif mode == 'rain_h':
            self._fx_rain_h(t, direction, audio_reactive, bands, num_bands)
        elif mode == 'spinner':
            self._fx_spinner(t, direction, audio_reactive, color, bands, num_bands, kwargs.get('arm_length', 0))
        elif mode == 'edge_walker':
            self._fx_edge_walker(t, direction, audio_reactive, color, bands, num_bands)
        elif mode == 'rain_shapes':
            self._fx_shapes(t, direction, audio_reactive, color, shape_type, bands, num_bands,
                            kwargs.get('move', 'h'), kwargs.get('sine_amp', 0))
        elif mode == 'crosshair':
            self._fx_crosshair(t, direction, audio_reactive, color, bands, num_bands)

    def _fx_scan(self, t, direction, audio_reactive, color, vertical, horizontal, bands, num_bands):
        rows = self.rows
        cols = self.cols
        _set = self._set_led
        _get_idx = self._physical_index
        _get_col = self._pal_color
        l_id = self.led_id

        if vertical:
            s_mod = 1.0 if cols > 10 else 0.4
            pos = (t * 15 * direction * s_mod) % cols
            thick = 1.2 if cols > 10 else 0.8
            for x in range(cols):
                dist = abs(x - pos)
                if dist < thick:
                    intensity = int((1.0 - (dist / thick)) * 255)
                    if audio_reactive: intensity = (intensity * (128 + bands[x % num_bands])) >> 8
                    c = _get_col(int((x / cols) * (self.pal_len - 1))) if color == 'auto' else color
                    for y in range(rows):
                        idx = _get_idx(l_id, x, y)
                        if idx >= 0: _set(idx, c, intensity)

        if horizontal:
            s_mod = 1.0 if rows > 10 else 0.5
            pos = (t * 25 * direction * s_mod) % rows
            thick = 2.5 if rows > 10 else 1.2
            for y in range(rows):
                dist = abs(y - pos)
                if dist < thick:
                    intensity = int((1.0 - (dist / thick)) * 255)
                    if audio_reactive: intensity = (intensity * (128 + bands[int(y * num_bands / rows)])) >> 8
                    c = _get_col(int((y / rows) * (self.pal_len - 1))) if color == 'auto' else color
                    for x in range(cols):
                        idx = _get_idx(l_id, x, y)
                        if idx >= 0: _set(idx, c, intensity)

    def _fx_diagonal(self, t, direction, audio_reactive, color, angle, bands, num_bands):
        rows = self.rows
        cols = self.cols
        _set = self._set_led
        _get_idx = self._physical_index
        _get_col = self._pal_color
        l_id = self.led_id

        cos_a = _fast_cos(angle) / 127.0
        sin_a = _fast_sin(angle) / 127.0
        proj_min = min(0.0, (cols-1)*cos_a) + min(0.0, (rows-1)*sin_a)
        proj_max = max(0.0, (cols-1)*cos_a) + max(0.0, (rows-1)*sin_a)
        p_range = proj_max - proj_min
        if p_range < 0.01: p_range = 0.01
        offset = (t * 20 * direction) % p_range
        thick = 3.5
        for row in range(rows):
            r_sin = row * sin_a
            for col in range(cols):
                proj = col * cos_a + r_sin - proj_min
                dist = abs(proj - offset)
                if dist > p_range * 0.5: dist = p_range - dist
                if dist < thick:
                    rel_p = proj / p_range
                    intensity = int((1.0 - (dist / thick)) * 255)
                    if audio_reactive: intensity = (intensity * (150 + bands[int(rel_p * (num_bands-1))])) >> 8
                    c = _get_col(int(rel_p * (self.pal_len - 1) + t * 20)) if color == 'auto' else color
                    idx = _get_idx(l_id, col, row)
                    if idx >= 0: _set(idx, c, intensity)

    def _fx_plasma(self, t, audio_reactive, bands, num_bands):
        rows = self.rows
        cols = self.cols
        _set = self._set_led
        _get_col = self._pal_color
        stab = _SIN_TAB
        idx_map = self._idx_map

        t_int = int(t * 40)
        row_s = [stab[(r * 10 + (t_int >> 1)) & 0xFF] for r in range(rows)]
        for col in range(cols):
            v_col = stab[(col * 10 + t_int) & 0xFF]
            col8 = col * 8
            for row in range(rows):
                v = v_col + row_s[row] + stab[(col8 + row * 8 + t_int) & 0xFF]
                v_n = (v + 381) // 3
                if v_n > 255: v_n = 255
                intensity = v_n
                if audio_reactive:
                    b_val = bands[(v_n * (num_bands-1)) >> 8]
                    intensity = (intensity * (150 + b_val)) >> 8
                pal_idx = (v_n * (self.pal_len-1) >> 8) + t_int
                idx = idx_map[row * cols + col]
                if idx >= 0: _set(idx, _get_col(pal_idx), intensity)

    def _fx_wave(self, t, audio_reactive, color, horizontal, bands, num_bands):
        rows = self.rows
        cols = self.cols
        _set = self._set_led
        _get_idx = self._physical_index
        _get_col = self._pal_color
        l_id = self.led_id
        stab = _SIN_TAB
        cx, cy = cols / 2.0, rows / 2.0

        t_phase = int(t * 60)
        if horizontal:
            for x in range(cols):
                y_off = (stab[(t_phase + x * 15) & 0xFF] * rows) >> 9
                if audio_reactive:
                    y_off = (y_off * (200 + bands[x % num_bands])) >> 8
                y_pos = cy + y_off
                c = _get_col(int(x * 15 + t * 30)) if color == 'auto' else color
                for y in range(max(0, int(y_pos-3)), min(rows, int(y_pos+4))):
                    dist = abs(y - y_pos)
                    intensity = int((1.0 - (dist / 3.0)) * 255)
                    if audio_reactive: intensity = (intensity * (150 + bands[x % num_bands])) >> 8
                    idx = _get_idx(l_id, x, y)
                    if idx >= 0: _set(idx, c, intensity)
        else:
            for y in range(rows):
                b_idx = int(y * num_bands / rows)
                x_off = (stab[(t_phase + y * 10) & 0xFF] * cols) >> 9
                if audio_reactive:
                    x_off = (x_off * (200 + bands[b_idx])) >> 8
                x_pos = cx + x_off
                c = _get_col(int(y * 5 + t * 30)) if color == 'auto' else color
                for x in range(max(0, int(x_pos-2)), min(cols, int(x_pos+3))):
                    dist = abs(x - x_pos)
                    intensity = int((1.0 - (dist / 2.0)) * 255)
                    if audio_reactive: intensity = (intensity * (150 + bands[b_idx])) >> 8
                    idx = _get_idx(l_id, x, y)
                    if idx >= 0: _set(idx, c, intensity)

    def _fx_shapes(self, t, direction, audio_reactive, color, shape_type, bands, num_bands,
                   move='h', sine_amp=0):
        rows = self.rows
        cols = self.cols
        _set = self._set_led
        _get_idx = self._physical_index
        _get_col = self._pal_color
        l_id = self.led_id

        shape = _SHAPE_SPARK
        if shape_type == 'diamond':                  shape = _SHAPE_DIAMOND
        elif shape_type == 'circle':                 shape = _SHAPE_RING
        elif shape_type == 'star':                   shape = _SHAPE_STAR
        elif shape_type in ('quadrat', 'square'):    shape = _SHAPE_CROSS_X
        elif shape_type == 'triangle':               shape = _SHAPE_COMET

        SHAPE_HALF_H = 2
        SHAPE_HALF_W = 3
        stab = _SIN_TAB
        sh_margin = 3
        self.aled.clear()

        if move == 'v':
            span_v = rows + sh_margin * 2
            base_spd = span_v / 5.0
            col_range = max(1, cols - SHAPE_HALF_W * 2 - 2)
            min_gap_c = SHAPE_HALF_W * 2 + 1
            n_try = max(4, cols // 4)
            dy_sign = 1 if direction < 0 else -1

            placed_c = []
            ccs = []
            for i in range(n_try):
                spd_i = base_spd * (0.7 + (i % 7) * 0.07)
                phase_i = (i * 97 + 31) % span_v
                cycle_i = (int(t * spd_i) + phase_i) // span_v
                cc_i = -1
                for attempt in range(20):
                    cc_try = SHAPE_HALF_W + 1 + (
                        (i * 73 + cycle_i * 97 + attempt * 43 + i * cycle_i * 17) % col_range)
                    ok = True
                    for p in placed_c:
                        if abs(cc_try - p) < min_gap_c:
                            ok = False
                            break
                    if ok:
                        placed_c.append(cc_try)
                        cc_i = cc_try
                        break
                ccs.append(cc_i)

            n = len(ccs)
            for i, cc in enumerate(ccs):
                if cc < 0:
                    continue
                spd = base_spd * (0.7 + (i % 7) * 0.07)
                if audio_reactive:
                    spd += (base_spd * bands[i % num_bands]) / 128.0
                phase = (i * 97 + 31) % span_v
                raw = (int(t * spd) + phase) % span_v
                if direction < 0:
                    raw = span_v - 1 - raw
                center_row = raw - sh_margin

                if sine_amp > 0:
                    off = int(stab[(int(t * spd * 20) + i * 43) & 0xFF] * sine_amp / 127)
                    cc = max(SHAPE_HALF_W, min(cols - 1 - SHAPE_HALF_W, cc + off))

                bass_br = (bands[i % num_bands] >> 1) if audio_reactive else 0
                col_c = _get_col(int(i * self.pal_len // n + t * 8)) if color == 'auto' else color
                for dy, dx, br in shape:
                    r2 = center_row + dy_sign * dy
                    c2 = cc + dx
                    if 0 <= r2 < rows and 0 <= c2 < cols:
                        pixel_br = min(255, br + bass_br) if audio_reactive else br
                        idx = _get_idx(l_id, c2, r2)
                        if idx >= 0: _set(idx, col_c, pixel_br)
        else:
            span = cols + sh_margin * 2
            base_spd = span / 5.0
            row_range = max(1, rows - SHAPE_HALF_H * 2 - 2)
            min_gap_r = SHAPE_HALF_H * 2 + 1
            n_try = max(4, rows // 2)
            dx_sign = 1 if direction < 0 else -1

            placed_r = []
            crs = []
            for i in range(n_try):
                spd_i = base_spd * (0.7 + (i % 7) * 0.07)
                phase_i = (i * 97 + 31) % span
                cycle_i = (int(t * spd_i) + phase_i) // span
                cr_i = -1
                for attempt in range(20):
                    cr_try = SHAPE_HALF_H + 1 + (
                        (i * 73 + cycle_i * 97 + attempt * 43 + i * cycle_i * 17) % row_range)
                    ok = True
                    for p in placed_r:
                        if abs(cr_try - p) < min_gap_r:
                            ok = False
                            break
                    if ok:
                        placed_r.append(cr_try)
                        cr_i = cr_try
                        break
                crs.append(cr_i)

            n = len(crs)
            for i, cr in enumerate(crs):
                if cr < 0:
                    continue
                spd = base_spd * (0.7 + (i % 7) * 0.07)
                if audio_reactive:
                    spd += (base_spd * bands[i % num_bands]) / 128.0
                phase = (i * 97 + 31) % span
                raw = (int(t * spd) + phase) % span
                if direction < 0:
                    raw = span - 1 - raw
                center_col = raw - sh_margin

                if sine_amp > 0:
                    off = int(stab[(int(t * spd * 20) + i * 43) & 0xFF] * sine_amp / 127)
                    cr = max(SHAPE_HALF_H, min(rows - 1 - SHAPE_HALF_H, cr + off))

                bass_br = (bands[i % num_bands] >> 1) if audio_reactive else 0
                col_r = _get_col(int(i * self.pal_len // n + t * 8)) if color == 'auto' else color
                for dy, dx, br in shape:
                    row2 = cr + dy
                    col2 = center_col + dx_sign * dx
                    if 0 <= row2 < rows and 0 <= col2 < cols:
                        pixel_br = min(255, br + bass_br) if audio_reactive else br
                        idx = _get_idx(l_id, col2, row2)
                        if idx >= 0: _set(idx, col_r, pixel_br)

    def _fx_radial(self, t, direction, audio_reactive, bands, num_bands):
        rows = self.rows
        cols = self.cols
        _set = self._set_led
        _get_idx = self._physical_index
        _get_col = self._pal_color
        l_id = self.led_id
        cx, cy = cols / 2.0, rows / 2.0

        bass = bands[0] if num_bands > 0 else 0
        thick = 1.5 + (bass >> 5)
        r = (t * 15 * direction) % (cols / 2 + rows / 2)
        for row in range(rows):
            dy2 = (row - cy) ** 2
            for col in range(cols):
                d = sqrt((col - cx) ** 2 + dy2)
                diff = abs(d - r)
                if diff < thick:
                    intensity = int((1.0 - (diff / thick)) * 255)
                    if audio_reactive: intensity = (intensity * (128 + bass)) >> 8
                    c = _get_col(int(d * 8 + t * 20))
                    idx = _get_idx(l_id, col, row)
                    if idx >= 0: _set(idx, c, intensity)

    def _fx_spiral(self, t, direction, audio_reactive, bands, num_bands):
        rows = self.rows
        cols = self.cols
        _set = self._set_led
        _get_idx = self._physical_index
        _get_col = self._pal_color
        l_id = self.led_id
        stab = _SIN_TAB
        cx, cy = cols / 2.0, rows / 2.0

        rot = t * 3.0 * direction
        arms = 3
        for row in range(rows):
            dy = row - cy
            for col in range(cols):
                dx = col - cx
                d2 = dx*dx + dy*dy
                if d2 < 1.0: continue
                d = sqrt(d2)
                ang = atan2(dy, dx)
                phase = int((ang - d * 0.2 + rot) * 40.74 * arms) & 0xFF
                val = stab[phase]
                if val > 80:
                    intensity = int(((val - 80) / 47.0) * 255)
                    if audio_reactive:
                        b_val = bands[int(d * num_bands / (rows + cols))]
                        intensity = (intensity * (128 + b_val)) >> 8
                    c = _get_col(int(d * 8 + t * 20))
                    idx = _get_idx(l_id, col, row)
                    if idx >= 0: _set(idx, c, intensity)

    def _fx_radar(self, t, direction):
        rows = self.rows
        cols = self.cols
        _set = self._set_led
        _get_idx = self._physical_index
        _get_col = self._pal_color
        l_id = self.led_id
        cx, cy = cols / 2.0, rows / 2.0

        sw_ang = (t * 4.0 * direction) % 6.28318
        for row in range(rows):
            dy = row - cy
            for col in range(cols):
                dx = col - cx
                d2 = dx*dx + dy*dy
                if d2 < 1.0: continue
                ang = atan2(dy, dx)
                diff = (ang - sw_ang) % 6.28318
                if diff < 0.8:
                    intensity = int(((0.8 - diff) / 0.8) * 255)
                    c = _get_col(int(sqrt(d2)*10 + t*10))
                    idx = _get_idx(l_id, col, row)
                    if idx >= 0: _set(idx, c, intensity)

    def _fx_noise(self, audio_reactive, bands, num_bands):
        rows = self.rows
        cols = self.cols
        _set = self._set_led
        _get_idx = self._physical_index
        _get_col = self._pal_color
        l_id = self.led_id

        energy = bands[51 % num_bands] if num_bands > 0 else 0
        count = 5 if not audio_reactive else int((energy / 255.0) * 30)
        for _ in range(count):
            rx = random.getrandbits(5) % cols
            ry = random.getrandbits(9) % rows
            idx = _get_idx(l_id, rx, ry)
            if idx >= 0: _set(idx, _get_col(random.getrandbits(9)), 255)

    def _fx_rain_v(self, t, direction, audio_reactive, bands, num_bands, speed=0.5):
        # speed: multiplier, 1.0 = baseline (~8s full cross), 0.5 = slow, 2.0 = fast
        rows = self.rows
        cols = self.cols
        _set = self._set_led
        _get_idx = self._physical_index
        _get_col = self._pal_color
        l_id = self.led_id
        self.aled.clear()
        trail = max(3, min(rows // 3, 8))
        base_spd = (rows / 50.0) * speed
        drops_per_col = max(1, rows // 12)
        t_sign = 1 if direction < 0 else -1
        for col in range(cols):
            for d in range(drops_per_col):
                seed = col * drops_per_col + d
                spd = base_spd * (0.7 + (seed % 7) * 0.07)
                if audio_reactive:
                    spd += base_spd * bands[col % num_bands] / 512.0
                offset = d * (rows // drops_per_col)
                raw_pos = int(t * spd) + col * 17 + offset
                cycle_v = raw_pos // rows
                head = raw_pos % rows
                base_color = _get_col((seed * self.pal_len // max(1, cols * drops_per_col) + cycle_v * 37) % self.pal_len)
                if direction < 0:
                    head = rows - 1 - head
                for tr in range(trail + 1):
                    row = head + t_sign * tr
                    if 0 <= row < rows:
                        bright = 255 - (tr * 255) // (trail + 1)
                        idx = _get_idx(l_id, col, row)
                        if idx >= 0: _set(idx, base_color, bright)

    def _fx_rain_h(self, t, direction, audio_reactive, bands, num_bands, speed=0.6):
        # speed: multiplier, 1.0 = baseline (~10s full cross), 0.5 = slow, 2.0 = fast
        rows = self.rows
        cols = self.cols
        _set = self._set_led
        _get_idx = self._physical_index
        _get_col = self._pal_color
        l_id = self.led_id
        self.aled.clear()
        trail = max(3, min(cols // 3, 8))
        span = cols + 2 * trail
        base_spd = (span / 50.0) * speed
        num_streams = min(rows * 2, 20)
        t_sign = 1 if direction < 0 else -1
        for s in range(num_streams):
            row = s * rows // num_streams
            spd = base_spd * (0.7 + (s % 7) * 0.07)
            phase = (s * 41) % span
            cycle = (int(t * spd) + phase) // span
            if audio_reactive:
                spd += base_spd * bands[row % num_bands] / 512.0
            raw = (int(t * spd) + phase) % span
            if direction < 0:
                raw = span - 1 - raw
            head = raw - trail
            base_color = _get_col((s * self.pal_len // max(1, num_streams) + cycle * 37) % self.pal_len)
            for tr in range(trail + 1):
                col = head + t_sign * tr
                if 0 <= col < cols:
                    bright = 255 - (tr * 255) // (trail + 1)
                    idx = _get_idx(l_id, col, row)
                    if idx >= 0: _set(idx, base_color, bright)

    def _fx_spinner(self, t, direction, audio_reactive, color, bands, num_bands,
                    arm_length=0, rotations_per_second=0.2):
        # rotations_per_second: how many full 360° rotations per second.
        # 0.2 = one rotation every 5s (gentle), 0.5 = one every 2s, 1.0 = one per second (fast)
        rows = self.rows
        cols = self.cols
        _set = self._set_led
        _get_idx = self._physical_index
        _get_col = self._pal_color
        l_id = self.led_id
        cx = cols / 2.0
        cy = rows / 2.0
        num_arms = 2
        if arm_length > 0:
            arm_len = float(arm_length)
        else:
            arm_len = max(cols, rows) * 0.45
        if audio_reactive and num_bands > 0:
            arm_len = arm_len * (0.6 + bands[0] / 640.0)
        # angular speed in rad/s derived from clean rotations_per_second
        angular_spd = rotations_per_second * 6.28318  # 2π rad per rotation
        base_angle = (t * angular_spd * direction) % 6.28318
        steps = max(int(arm_len * 2.5), 8)
        inv_steps = 1.0 / steps
        for arm in range(num_arms):
            arm_angle = base_angle + arm * 6.28318 / num_arms
            cos_a = _fast_cos(arm_angle) / 127.0
            sin_a = _fast_sin(arm_angle) / 127.0
            c = _get_col(int(arm * self.pal_len // num_arms + t * 20)) if color == 'auto' else color
            for step in range(-steps, steps + 1):
                frac = step * inv_steps
                ci = int(cx + frac * arm_len * cos_a + 0.5)
                ri = int(cy + frac * arm_len * sin_a + 0.5)
                if 0 <= ci < cols and 0 <= ri < rows:
                    bright = int(255 * (1.0 - abs(frac) * 0.35))
                    idx = _get_idx(l_id, ci, ri)
                    if idx >= 0: _set(idx, c, bright)

    def _fx_edge_walker(self, t, direction, audio_reactive, color, bands, num_bands):
        rows = self.rows
        cols = self.cols
        _set = self._set_led
        _get_idx = self._physical_index
        _get_col = self._pal_color
        l_id = self.led_id
        # Traces the physical concentric outer ring or perimeter path
        if self._edge_path is None:
            self._edge_path = self._build_ring_path(0)
        path = self._edge_path
        path_len = len(path)
        if path_len == 0: return
        num_walkers = 2
        trail = 7
        base_spd = path_len / 25.0  # one full loop in ~10s  (was /55)
        for w in range(num_walkers):
            speed = base_spd * (1.0 + w * 0.6)
            if audio_reactive:
                speed += base_spd * bands[w % num_bands] / 512.0
            pos = int(t * speed + w * path_len // num_walkers) % path_len
            if direction < 0:
                pos = path_len - 1 - pos
            c_pal = _get_col(int(w * self.pal_len // num_walkers + t * 10)) if color == 'auto' else color
            for tr in range(trail + 1):
                edge_pos = (pos - tr if direction >= 0 else pos + tr) % path_len
                col, row = path[edge_pos]
                bright = 255 - (tr * 255) // (trail + 1)
                idx = _get_idx(l_id, col, row)
                if idx >= 0: _set(idx, c_pal, bright)


    def _fx_crosshair(self, t, direction, audio_reactive, color, bands, num_bands,
                      h_arm=4, v_arm=4, gap=0):
        """Sniper crosshair — wanders organically, reacts to bass (jitter) and mid (push)."""
        rows = self.rows
        cols = self.cols
        _set = self._set_led
        _get_idx = self._physical_index
        _get_col = self._pal_color
        l_id = self.led_id
        h_arm = max(1, h_arm)
        v_arm = max(1, min(v_arm, (rows - 1) // 2))
        gap = max(0, min(gap, h_arm - 1, v_arm - 1))

        now = time.ticks_ms()

        # Lazy-init: A→pause→B→pause→C waypoint state machine
        if not hasattr(self, '_cross_cx') or self._cross_cx is None:
            self._cross_cx = float(cols // 2)
            self._cross_cy = float(rows // 2)
            self._cross_tx = float(cols // 2)
            self._cross_ty = float(rows // 2)
            self._cross_speed = 0.15
            self._cross_paused = True
            self._cross_timer = now
            self._cross_pause_ms = 400
            self._cross_last_ms = now

        dt = time.ticks_diff(now, self._cross_last_ms)
        self._cross_last_ms = now
        if dt <= 0 or dt > 500: dt = 33

        bright = 255
        speed_mult = 1
        if audio_reactive and num_bands > 0:
            bass = bands[0]
            bright = min(255, 160 + (bass >> 2))
            speed_mult = 1.0 + (bass / 255.0)
            if self._cross_paused and bass > 210:
                self._cross_pause_ms = 0   # strong beat → snap to next target immediately

        if self._cross_paused:
            if time.ticks_diff(now, self._cross_timer) >= self._cross_pause_ms:
                r8 = random.getrandbits(8)
                # Target positions use full display range; arm drawing clips at edges naturally
                rand_x = float(random.getrandbits(7) * cols // 127)   # 0..cols-1
                rand_y = float(random.getrandbits(7) * rows // 127)   # 0..rows-1
                off_h  = float(cols + h_arm + 4)                      # off right
                off_hn = float(-h_arm - 4)                            # off left
                off_v  = float(rows + v_arm + 4)                      # off bottom
                off_vn = float(-v_arm - 4)                            # off top
                if r8 < 38:   # ~15%: sweep fully off a horizontal edge
                    self._cross_tx = off_hn if random.getrandbits(1) else off_h
                    self._cross_ty = rand_y
                elif r8 < 77:  # ~15%: sweep fully off a vertical edge
                    self._cross_tx = rand_x
                    self._cross_ty = off_vn if random.getrandbits(1) else off_v
                else:           # 70%: land somewhere within display
                    self._cross_tx = rand_x
                    self._cross_ty = rand_y
                self._cross_speed = 0.05 + (random.getrandbits(4) * 0.005)  # 0.05–0.38 px/ms
                self._cross_paused = False
        else:
            dx = self._cross_tx - self._cross_cx
            dy = self._cross_ty - self._cross_cy
            dist2 = dx * dx + dy * dy
            step = self._cross_speed * speed_mult * dt
            if dist2 <= (step + 0.5) * (step + 0.5):
                self._cross_cx = self._cross_tx
                self._cross_cy = self._cross_ty
                self._cross_paused = True
                self._cross_timer = now
                self._cross_pause_ms = 150 + (random.getrandbits(8) * 4)  # 150–1170ms
            else:
                dist = sqrt(dist2)
                self._cross_cx += dx / dist * step
                self._cross_cy += dy / dist * step

        cx = int(self._cross_cx)
        cy = int(self._cross_cy)

        c = _get_col(int(t * 15)) if color == 'auto' else color

        # Horizontal arms (left and right, skipping center gap)
        for dx in range(-h_arm, h_arm + 1):
            if -gap <= dx <= gap:
                continue
            x = cx + dx
            if 0 <= x < cols:
                idx = _get_idx(l_id, x, cy)
                if idx >= 0: _set(idx, c, bright)

        # Vertical arms (top and bottom, skipping center gap)
        for dy in range(-v_arm, v_arm + 1):
            if -gap <= dy <= gap:
                continue
            y = cy + dy
            if 0 <= y < rows:
                idx = _get_idx(l_id, cx, y)
                if idx >= 0: _set(idx, c, bright)

    # ============ ORBITAL DOTS EFFECT ============

    def _build_ring_path(self, ring=0):
        """Closed (or bounce) perimeter path for orbital effects.

        LED1 (5 rows × N cols):
          ring=0 → outer perimeter.
          ring=1 → rows 1–2 racetrack (full column width).
          ring=2 → bounce path on row 3 (inner arc, knight-rider).
        LED2 (138 rows × 3 cols):
          ring=0 → outer perimeter (cols 0,2 + top/bottom).
          ring>=1 → serpentine col0↓ col1↑ col2↓ (uses middle column).
        General: ring = depth from outer edge."""
        rows = self.rows
        cols = self.cols
        d = max(0, int(ring))

        # 19x19 custom matrix layout (LED1 19x19 concentric ring mapping)
        if rows == 19 and cols == 19:
            coord_map = {}
            _gidx = self._physical_index
            _lid = self.led_id
            for r in range(19):
                for c in range(19):
                    idx = _gidx(_lid, c, r)
                    if idx >= 0:
                        coord_map[idx] = (c, r)
            
            path = []
            if d == 0:
                # Ring 0: indices 0..36
                for i in range(37):
                    if i in coord_map:
                        path.append(coord_map[i])
            elif d == 1:
                # Ring 1: indices 49..71 (lower inner ring)
                for i in range(49, 72):
                    if i in coord_map:
                        path.append(coord_map[i])
            else:
                # Ring 2+: indices 37..48 (upper inner ring)
                for i in range(37, 49):
                    if i in coord_map:
                        path.append(coord_map[i])
            return path

        # 3-column displays (LED2): serpentine through all 3 cols
        if cols == 3 and d >= 1:
            path = []
            for r in range(rows):            path.append((0, r))
            for r in range(rows-1, -1, -1):  path.append((1, r))
            for r in range(rows):            path.append((2, r))
            return path

        # 5-row displays (LED1 matrix): custom inner paths
        if rows == 5:
            if d == 1:
                # Racetrack rows 1,2 — full column width
                path = []
                for c in range(cols):            path.append((c, 1))
                path.append((cols-1, 2))
                for c in range(cols-2, -1, -1):  path.append((c, 2))
                return path
            if d >= 2:
                # Bounce/ping-pong path on row 3 (inner arc, knight-rider)
                path = []
                for c in range(cols):           path.append((c, 3))
                for c in range(cols-2, 0, -1):  path.append((c, 3))
                return path

        # General: rectangular perimeter at depth d
        r0, r1, c0, c1 = d, rows-1-d, d, cols-1-d
        if r0 >= r1 or c0 >= c1:
            r0, r1, c0, c1 = 0, rows-1, 0, cols-1
        path = []
        for c in range(c0, c1+1):        path.append((c, r0))
        for r in range(r0+1, r1+1):      path.append((c1, r))
        for c in range(c1-1, c0-1, -1):  path.append((c, r1))
        for r in range(r1-1, r0, -1):    path.append((c0, r))
        return path

    def _get_orb_color(self, colors, i, n):
        """Return (r,g,b) for index i. 'R'/'auto'=palette cycle, 'RM'=stored random."""
        if isinstance(colors, str):
            if colors in ('R', 'auto'):
                idx = (self._orb_pal_off + (i * self.pal_len // max(1, n))) % max(1, self.pal_len)
                return self._pal_color(idx)
            return (int(self._orb_cr[i % max(1, len(self._orb_cr))]),
                    int(self._orb_cg[i % max(1, len(self._orb_cg))]),
                    int(self._orb_cb[i % max(1, len(self._orb_cb))]))
        if isinstance(colors, (list, tuple)) and len(colors) > 0:
            if isinstance(colors[0], int):
                return (int(colors[0]), int(colors[1]), int(colors[2]))
            col = colors[i % len(colors)]
            return (int(col[0]), int(col[1]), int(col[2]))
        return (255, 255, 255)

    def render_orbital_dots(self, n_dots=4, ring=0, direction=1, speed=2.0,
                             colors='R', mode='dots', ghosting=0.7,
                             trail=4, audio_reactive=True, pulse=True,
                             dot_mode=None, color=None):
        """N dots orbiting evenly on a perimeter ring.

        mode='dots'  — comet-trail dots (direction-aware trail).
                       Uses cached LED indices — no per-frame index lookups.
        mode='paint' — stateless wiper: color boundary sweeps the full path,
                       reverses on each pass with the next palette color.
                       Pass colors=[(255,255,255),(200,0,0)] for white-red flag.

        ring: 0=outer edge, 1=inner racetrack (LED1: rows1-2; LED2: serpentine),
              2=inner arc bounce (LED1: row3 knight-rider).
        """
        if color is not None:
            colors = color
        if dot_mode is not None:
            mode = dot_mode
        now = time.ticks_ms()

        # ── Lazy build ring path + pre-cache LED indices ─────────────────
        rebuild = (not hasattr(self, '_orb_ring') or self._orb_ring is None
                   or self._orb_ring != ring)
        if rebuild:
            path = self._build_ring_path(ring)
            plen = len(path)
            self._orb_path_c   = bytearray(plen)
            self._orb_path_r   = bytearray(plen)
            self._orb_path_idx = array.array('i', [0] * plen)
            _gidx = self._physical_index
            _lid  = self.led_id
            for i in range(plen):
                self._orb_path_c[i] = path[i][0]
                self._orb_path_r[i] = path[i][1]
                self._orb_path_idx[i] = _gidx(_lid, path[i][0], path[i][1])
            self._orb_path_len = plen
            self._orb_ring     = ring
            self._orb_phase    = 0.0
            self._orb_wipe_tot = 0.0
            self._orb_last_ms  = now
            self._orb_pal_off  = 0
            self._orb_n_dots   = -1

        plen   = self._orb_path_len
        n_dots = max(1, min(int(n_dots), plen))

        # ── Init random colors once per n_dots ───────────────────────────
        if not hasattr(self, '_orb_n_dots') or self._orb_n_dots != n_dots:
            self._orb_n_dots = n_dots
            self._orb_cr = bytearray(max(1, n_dots))
            self._orb_cg = bytearray(max(1, n_dots))
            self._orb_cb = bytearray(max(1, n_dots))
            if isinstance(colors, str) and colors == 'RM':
                for i in range(n_dots):
                    col = self._pal_color(random.getrandbits(9) % max(1, self.pal_len))
                    self._orb_cr[i], self._orb_cg[i], self._orb_cb[i] = col[0], col[1], col[2]

        # ── Timing + audio ────────────────────────────────────────────────
        dt = time.ticks_diff(now, self._orb_last_ms)
        self._orb_last_ms = now
        if dt <= 0 or dt > 500: dt = 33

        bass_bright = 255
        eff_speed = speed
        if audio_reactive and self.c.mv_feat[51]:
            bands = self.c.mv_bands
            bass = int(bands[0]) if len(bands) > 0 else 0
            eff_speed = speed * (0.5 + bass / 170.0)
            if pulse:
                bass_bright = min(255, 80 + bass)

        if isinstance(colors, str) and colors != 'RM':
            self._orb_pal_off = (self._orb_pal_off + 2) % max(1, self.pal_len)

        # ── Clear / ghosting ──────────────────────────────────────────────
        self._ghosting_or_clear(ghosting > 0, ghosting)

        path_idx = self._orb_path_idx
        _set = self._set_led

        # ══════════════════════════════════════════════════════════════════
        if mode == 'paint':
            # Stateless wiper: sweeps a color boundary L↔R, flipping each
            # full pass. Colors cycle per pass. No per-pixel buffer needed.
            if not hasattr(self, '_orb_wipe_tot'):
                self._orb_wipe_tot = 0.0
            self._orb_wipe_tot += eff_speed * dt * plen / 1000.0
            total      = self._orb_wipe_tot
            wipe_cycle = int(total) // plen
            wipe_pos   = int(total) % plen

            # Resolve the two fill colors for this cycle
            if (isinstance(colors, (list, tuple)) and len(colors) > 0
                    and not isinstance(colors[0], int)):
                n_c = len(colors)
                ca = self._get_orb_color(colors, wipe_cycle % n_c, n_c)
                cb = self._get_orb_color(colors, (wipe_cycle+1) % n_c, n_c)
            else:
                pal_half = max(1, self.pal_len // 2)
                pal_step = max(1, self.pal_len // 4)
                ca_i = (wipe_cycle * pal_step + self._orb_pal_off) % max(1, self.pal_len)
                cb_i = (ca_i + pal_half) % max(1, self.pal_len)
                ca = self._pal_color(ca_i)
                cb = self._pal_color(cb_i)

            if wipe_cycle % 2 == 0:
                boundary = wipe_pos         # sweeping right
                c_left, c_right = ca, cb
            else:
                boundary = plen-1-wipe_pos  # sweeping left
                c_left, c_right = cb, ca

            for seg in range(plen):
                fill_col = c_left if seg <= boundary else c_right
                led = int(path_idx[seg])
                if led >= 0: _set(led, fill_col, bass_bright)
            # Bright white dot marks the leading edge
            edge_led = int(path_idx[boundary % plen])
            if edge_led >= 0: _set(edge_led, (255, 255, 255), bass_bright)

        # ══════════════════════════════════════════════════════════════════
        else:
            dpdt = (plen / 1000.0) * eff_speed * direction
            self._orb_phase = (self._orb_phase + dpdt * dt) % plen
            if self._orb_phase < 0.0: self._orb_phase += plen

            trail_len = max(0, int(trail))
            trail_dir = -1 if direction >= 0 else 1
            spacing   = plen / n_dots

            for i in range(n_dots):
                pos_f = (self._orb_phase + i * spacing) % plen
                ci = self._get_orb_color(colors, i, n_dots)

                for tr in range(trail_len + 1):
                    tr_pos = int((pos_f + trail_dir * tr) % plen)
                    bright = bass_bright if tr == 0 else (bass_bright * (trail_len+1-tr)) // (trail_len+1)
                    if bright < 4: continue
                    led = int(path_idx[tr_pos])
                    if led >= 0: _set(led, ci, bright)

    # ============ SNAKE EFFECTS ============
    def colored_snake(self, num_snakes=3, colors='R', bg_color=(0, 0, 0),
                      min_len=5, max_len=30, delay=30, directions=None):
        """
        Multiple colored snake segments traversing the strip independently.

        num_snakes:  number of snakes
        colors:      tuple | list-of-tuples | 'R' (palette cycle) | 'RM' (random)
        bg_color:    background color
        min_len:     minimum body length in LEDs
        max_len:     maximum body length in LEDs
        delay:       base step interval in ms (each snake gets a random variant)
        directions:  None = random per snake | 1 | -1 | (1, -1, ...) list

        Fill modes cycle across snakes:
          0 = solid   (fast_fill_segment)
          1 = gradient head->bg_color tail
          2 = flag    (3 colour bands)
        """
        sl = self.segment_length
        ao = self.aled_object
        if ao is None:
            return

        # ── Lazy init / reinit when snake count changes ──────────────────────
        if not hasattr(self, '_snk_n') or self._snk_n != num_snakes:
            self._snk_n = num_snakes
            self._snk_pos = array.array('h', [0] * num_snakes)
            self._snk_len = array.array('h', [0] * num_snakes)
            self._snk_dir = array.array('b', [0] * num_snakes)
            self._snk_fm = array.array('b', [0] * num_snakes)
            self._snk_dly = array.array('i', [0] * num_snakes)
            self._snk_time = array.array('I', [0] * num_snakes)
            self._snk_pal = array.array('h', [0] * num_snakes)
            self._snk_cr = bytearray(num_snakes)
            self._snk_cg = bytearray(num_snakes)
            self._snk_cb = bytearray(num_snakes)
            self._snk_cr2 = bytearray(num_snakes)
            self._snk_cg2 = bytearray(num_snakes)
            self._snk_cb2 = bytearray(num_snakes)

            pal_len = getattr(self, 'pal_length', 256)
            max_l = max(min_len + 1, min(max_len, max(min_len + 1, sl // max(2, num_snakes))))
            now = time.ticks_ms()
            is_tuple_list = (isinstance(colors, (list, tuple)) and
                             len(colors) > 0 and isinstance(colors[0], tuple))

            for i in range(num_snakes):
                self._snk_pos[i] = random.randint(0, sl - 1)
                self._snk_len[i] = random.randint(min_len, max_l)

                if directions is None:
                    d = 1 if random.random() < 0.5 else -1
                elif isinstance(directions, (list, tuple)):
                    d = directions[i % len(directions)]
                else:
                    d = int(directions)
                self._snk_dir[i] = d

                self._snk_fm[i] = i % 3
                self._snk_dly[i] = max(10, int(delay * (0.5 + random.random() * 1.5)))
                self._snk_time[i] = now

                pal_off = (i * pal_len // num_snakes) % pal_len
                self._snk_pal[i] = pal_off

                if is_tuple_list:
                    c = colors[i % len(colors)]
                    c2 = colors[(i + 1) % len(colors)]
                else:
                    c = self.color_return(colors, color_offset=pal_off)
                    c2 = self.color_return(colors, color_offset=(pal_off + pal_len // 3) % pal_len)

                self._snk_cr[i] = c[0];
                self._snk_cg[i] = c[1];
                self._snk_cb[i] = c[2]
                self._snk_cr2[i] = c2[0];
                self._snk_cg2[i] = c2[1];
                self._snk_cb2[i] = c2[2]

        # ── Clear background ─────────────────────────────────────────────────
        if bg_color == (0, 0, 0):
            ao.clear()
        else:
            ao.aled_fill(bg_color)

        # ── Draw and update each snake ────────────────────────────────────────
        now = time.ticks_ms()
        for i in range(self._snk_n):
            head = int(self._snk_pos[i])
            slen = int(self._snk_len[i])
            sdir = int(self._snk_dir[i])
            fm = int(self._snk_fm[i])
            c1 = (self._snk_cr[i], self._snk_cg[i], self._snk_cb[i])
            c2 = (self._snk_cr2[i], self._snk_cg2[i], self._snk_cb2[i])

            if fm == 0:
                # ── solid: fast_fill_segment, split on wrap ───────────────
                if sdir == 1:
                    start = (head - slen + 1) % sl
                    if start <= head:
                        ao.fast_fill_segment(start, head + 1, c1)
                    else:
                        ao.fast_fill_segment(start, sl, c1)
                        ao.fast_fill_segment(0, head + 1, c1)
                else:
                    end = (head + slen - 1) % sl
                    if head <= end:
                        ao.fast_fill_segment(head, end + 1, c1)
                    else:
                        ao.fast_fill_segment(head, sl, c1)
                        ao.fast_fill_segment(0, end + 1, c1)

            elif fm == 1:
                # ── gradient: head = c1, tail fades to bg_color ───────────
                for j in range(slen):
                    p = (head - sdir * j) % sl
                    t = j / max(1, slen - 1)
                    self._set_led(p, (
                        int(c1[0] + (bg_color[0] - c1[0]) * t),
                        int(c1[1] + (bg_color[1] - c1[1]) * t),
                        int(c1[2] + (bg_color[2] - c1[2]) * t),
                    ))

            else:
                # ── flag: 3 colour bands ──────────────────────────────────
                band = max(1, slen // 3)
                c3 = ((c1[0] + c2[0]) >> 1, (c1[1] + c2[1]) >> 1, (c1[2] + c2[2]) >> 1)
                for j in range(slen):
                    col = c1 if j < band else (c3 if j < band * 2 else c2)
                    self._set_led((head - sdir * j) % sl, col)

            # ── advance snake on its own timer ────────────────────────────
            if time.ticks_diff(now, self._snk_time[i]) >= self._snk_dly[i]:
                self._snk_pos[i] = (head + sdir) % sl
                self._snk_time[i] = now
                # cycle palette for 'R' mode
                if isinstance(colors, str) and colors == 'R':
                    pal_len = getattr(self, 'pal_length', 256)
                    new_off = (int(self._snk_pal[i]) + 1) % pal_len
                    self._snk_pal[i] = new_off
                    c = self.color_return(colors, color_offset=new_off)
                    c2 = self.color_return(colors, color_offset=(new_off + pal_len // 3) % pal_len)
                    self._snk_cr[i] = c[0];
                    self._snk_cg[i] = c[1];
                    self._snk_cb[i] = c[2]
                    self._snk_cr2[i] = c2[0];
                    self._snk_cg2[i] = c2[1];
                    self._snk_cb2[i] = c2[2]

    def render_particle_attractor(self, mass=100, particles=75, size=1,
                                   friction=8, color_by_age=False,
                                   move_attractor=False, swallow=False,
                                   ghosting=0.85):
        # Redesigned for narrow (3-col) displays: Y is the only physics axis.
        # X column = particle_index % cols — gives 3 clearly separated streams.
        # Attractor moves along Y, pulling all 3 streams toward it.
        MAX_P = max(30, min(90, particles))
        MAX_TTL = 200

        rows = self.rows
        cols = self.cols
        rows_f = float(rows - 1)

        SOURCE_SPEED = 3.0   # px / sim-step along Y
        EMIT_VY      = 4.0   # initial emission speed (px / sim-step)

        if getattr(self, '_at_max_p', -1) != MAX_P:
            self._at_max_p  = MAX_P
            self._at_py     = array.array('f', [0.0] * MAX_P)
            self._at_pvy    = array.array('f', [0.0] * MAX_P)
            self._at_pttl   = array.array('h', [0]   * MAX_P)
            self._at_phue   = bytearray(MAX_P)
            self._at_pused  = 0
            self._at_sy     = float(rows) * 0.25
            self._at_svy    = SOURCE_SPEED
            self._at_ay     = float(rows) * 0.5
            self._at_avy    = SOURCE_SPEED * 0.35
            self._at_frame  = 0

        frame = self._at_frame

        # Source: bounces along Y
        self._at_sy += self._at_svy
        if self._at_sy <= 0.0:
            self._at_sy = 0.0
            self._at_svy = abs(self._at_svy) + (random.getrandbits(3) - 3) * 0.15
        elif self._at_sy >= rows_f:
            self._at_sy = rows_f
            self._at_svy = -abs(self._at_svy) + (random.getrandbits(3) - 3) * 0.15
        sv = abs(self._at_svy)
        if sv > SOURCE_SPEED * 1.6:
            self._at_svy = self._at_svy * SOURCE_SPEED * 1.6 / sv

        # Attractor: fixed center, or slow oscillation along Y
        if move_attractor:
            self._at_avy += (random.getrandbits(3) - 3) * 0.06
            self._at_ay  += self._at_avy
            lo = rows * 0.12; hi = rows * 0.88
            if self._at_ay < lo:
                self._at_ay = lo; self._at_avy = abs(self._at_avy)
            elif self._at_ay > hi:
                self._at_ay = hi; self._at_avy = -abs(self._at_avy)
            av = abs(self._at_avy)
            if av > SOURCE_SPEED * 0.55:
                self._at_avy = self._at_avy * SOURCE_SPEED * 0.55 / av
        else:
            self._at_ay = float(rows) * 0.5

        ay = self._at_ay

        # Emit 2 particles per frame — one per target column each other frame
        for emit_pass in range(2):
            col_emit = (frame + emit_pass) % cols
            slot = -1
            for j in range(col_emit, MAX_P, cols):
                if self._at_pttl[j] <= 0:
                    slot = j; break
            if slot < 0:
                for j in range(MAX_P):
                    if self._at_pttl[j] <= 0:
                        slot = j; break
            if slot >= 0:
                vy0 = EMIT_VY if self._at_svy >= 0 else -EMIT_VY
                vy0 += (random.getrandbits(4) - 7) * 0.4
                self._at_py[slot]   = self._at_sy
                self._at_pvy[slot]  = vy0
                self._at_pttl[slot] = MAX_TTL - (random.getrandbits(6) * 2)
                col_actual = slot % cols
                self._at_phue[slot] = (col_actual * 85 + (frame >> 4)) & 0xFF
                if slot >= self._at_pused:
                    self._at_pused = slot + 1

        # Audio: bass boosts attractor pull
        is_active = self.c.mv_feat[51]
        base_force = (mass / 255.0) * 1.2
        if is_active:
            bass = self.c.mv_feat[48]
            force_scale = base_force * (1.0 + float(bass) / 100.0)
        else:
            force_scale = base_force
        fric_coeff = 1.0 - friction * 0.002

        for i in range(self._at_pused):
            ttl = self._at_pttl[i]
            if ttl <= 0:
                continue
            dy = ay - self._at_py[i]
            dist = abs(dy)
            if swallow and dist < 2.0:
                self._at_pttl[i] = 0
                continue
            if dist > 0.1:
                f = force_scale / (dist * 0.03 + 0.5)
                self._at_pvy[i] += f if dy > 0 else -f
            self._at_pvy[i] *= fric_coeff
            v = self._at_pvy[i]
            if v > 8.0:   self._at_pvy[i] = 8.0
            elif v < -8.0: self._at_pvy[i] = -8.0
            self._at_py[i] += self._at_pvy[i]
            if self._at_py[i] < 0.0:
                self._at_py[i] = 0.0
                self._at_pvy[i] = abs(self._at_pvy[i]) * 0.6
            elif self._at_py[i] > rows_f:
                self._at_py[i] = rows_f
                self._at_pvy[i] = -abs(self._at_pvy[i]) * 0.6
            self._at_pttl[i] = ttl - 1

        while self._at_pused > 0 and self._at_pttl[self._at_pused - 1] <= 0:
            self._at_pused -= 1

        self._at_frame = (frame + 1) & 0xFFFF


        ay = self._at_ay
        self._ghosting_or_clear(ghosting > 0, ghosting)
        _set = self._set_led
        _get_idx = self._physical_index
        l_id = self.led_id
        gb = self.brightness
        pal_len = self.pal_len

        for i in range(self._at_pused):
            if self._at_pttl[i] <= 0:
                continue
            y = int(self._at_py[i] + 0.5)
            x = i % cols
            if not (0 <= y < rows):
                continue
            if color_by_age:
                pal_idx = ((MAX_TTL - self._at_pttl[i]) * (pal_len - 1) // MAX_TTL) % pal_len
            else:
                pal_idx = (int(self._at_phue[i]) * pal_len) >> 8
            color = self._pal_color(pal_idx)
            idx = _get_idx(l_id, x, y)
            if idx >= 0:
                _set(idx, color, gb)
            if size > 0:
                for dy2 in (-1, 1):
                    ny = y + dy2
                    if 0 <= ny < rows:
                        idx2 = _get_idx(l_id, x, ny)
                        if idx2 >= 0:
                            _set(idx2, color, gb >> 2)

        # Attractor: bright white band across all 3 columns
        aj = int(ay + 0.5)
        if 0 <= aj < rows:
            for x in range(cols):
                idx = _get_idx(l_id, x, aj)
                if idx >= 0:
                    self.aled[idx] = self._calc_brightness((255, 255, 255), gb)

    def render_dna_spiral(self, scroll_speed=8.0, cycles=3, rung_spacing=0,
                           enable_ghosting=True, ghosting_factor=0.72,
                           audio_reactive=True):
        is_active = self.c.mv_feat[51]
        bands = self.c.mv_bands
        now = time.ticks_ms()
        t = now / 1000.0
        rows = self.rows
        cols = self.cols
        eff_speed = scroll_speed
        gb = self.brightness
        if audio_reactive and is_active:
            bass = float(bands[0]) if len(bands) > 0 else 0.0
            eff_speed = scroll_speed * (0.4 + bass / 170.0)
            gb = min(255, int(self.brightness * (0.5 + bass / 510.0)))
        self._ghosting_or_clear(enable_ghosting, ghosting_factor)
        scroll = t * eff_speed
        pal_len = self.pal_len
        _get_idx = self._physical_index
        l_id = self.led_id
        _set = self._set_led
        stab = _SIN_TAB
        t25 = int(t * 25)
        tall = rows >= cols
        if tall:
            long_len = rows
            short_len = cols
            helix_freq = (cycles * 6.28318) / max(1, long_len)
            cx = (short_len - 1) * 0.5
            amp = cx
            rs = rung_spacing if rung_spacing > 0 else max(4, long_len // 20)
            for y in range(long_len):
                lut = int((y * helix_freq + scroll) * 40.7436) & 0xFF
                sa = stab[lut]
                sb = stab[(lut + 128) & 0xFF]
                ca = max(0, min(short_len - 1, int(cx + amp * sa / 127.0 + 0.5)))
                cb = max(0, min(short_len - 1, int(cx + amp * sb / 127.0 + 0.5)))
                pal_row = (y * pal_len // long_len + t25) % pal_len
                color_a = self._pal_color(pal_row)
                color_b = self._pal_color((pal_row + pal_len // 2) % pal_len)
                idx = _get_idx(l_id, ca, y)
                if idx >= 0: _set(idx, color_a, gb)
                if cb != ca:
                    idx = _get_idx(l_id, cb, y)
                    if idx >= 0: _set(idx, color_b, gb)
                if y % rs == 0:
                    rung_br = gb >> 1
                    x0 = ca if ca <= cb else cb
                    x1 = cb if ca <= cb else ca
                    for x in range(x0, x1 + 1):
                        idx = _get_idx(l_id, x, y)
                        if idx >= 0: _set(idx, (180, 180, 180), rung_br)
        else:
            long_len = cols
            short_len = rows
            helix_freq = (cycles * 6.28318) / max(1, long_len)
            cy = (short_len - 1) * 0.5
            amp = cy
            rs = rung_spacing if rung_spacing > 0 else max(2, long_len // 20)
            for x in range(long_len):
                lut = int((x * helix_freq + scroll) * 40.7436) & 0xFF
                sa = stab[lut]
                sb = stab[(lut + 128) & 0xFF]
                ra = max(0, min(short_len - 1, int(cy + amp * sa / 127.0 + 0.5)))
                rb = max(0, min(short_len - 1, int(cy + amp * sb / 127.0 + 0.5)))
                pal_col = (x * pal_len // long_len + t25) % pal_len
                color_a = self._pal_color(pal_col)
                color_b = self._pal_color((pal_col + pal_len // 2) % pal_len)
                idx = _get_idx(l_id, x, ra)
                if idx >= 0: _set(idx, color_a, gb)
                if rb != ra:
                    idx = _get_idx(l_id, x, rb)
                    if idx >= 0: _set(idx, color_b, gb)
                if x % rs == 0:
                    rung_br = gb >> 1
                    y0 = ra if ra <= rb else rb
                    y1 = rb if ra <= rb else ra
                    for y in range(y0, y1 + 1):
                        idx = _get_idx(l_id, x, y)
                        if idx >= 0: _set(idx, (180, 180, 180), rung_br)

    def render_ps_fire(self, cooling=175, sparking=80, audio_reactive=False, speed=2.0):
        rows = self.rows
        cols = self.cols
        # Determine scale based on height to keep fire simulation grid around 30-50 rows
        if rows >= 45:
            scale = 3
        else:
            scale = 1
        fire_rows = (rows + scale - 1) // scale
        n = fire_rows * cols

        if self._fire_heat is None or len(self._fire_heat) != n or self._fire_idx is None:
            self._fire_heat = bytearray(n)
            self._fire_accum = 0.0
            self._fire_rand_seed = 170623
            # Pre-seed bottom half so fire appears immediately
            fh0 = self._fire_heat
            for sy in range(fire_rows - fire_rows // 2, fire_rows):
                rb = sy * cols
                for sx in range(cols):
                    fh0[rb + sx] = 255
            # Cool table: 64 random bytes, reused instead of per-cell random.randint
            self._fire_cool_table = bytearray(64)
            for i in range(64):
                self._fire_cool_table[i] = random.randint(0, 255)
            self._fire_frame = 0
            self._fire_tick = 0
            # Precompute LED index cache: fire_rows × cols × scale entries
            self._fire_idx = array.array('h', [0] * (n * scale))
            led_arr = getattr(self.led, 'array', None)  # tuple-of-tuples for led1, None for led2
            _gi = self._physical_index
            l_id = self.led_id
            ci = 0
            for fy in range(fire_rows):
                for fx in range(cols):
                    for dy in range(scale):
                        phy_y = (fire_rows - 1 - fy) * scale + dy
                        if 0 <= phy_y < rows:
                            self._fire_idx[ci] = led_arr[phy_y][fx] if led_arr is not None else _gi(l_id, fx, phy_y)
                        else:
                            self._fire_idx[ci] = -1
                        ci += 1
            # Spark system
            self._fs_data = array.array('i', [0] * 30)
            self._fs_br = bytearray(15)
            self._fs_x = bytearray(15)
            self._fs_count = 0

        eff_sparking = sparking
        eff_cooling = cooling
        if audio_reactive and self.c.mv_feat[51]:
            bands = self.c.mv_bands
            bass = bands[0] if len(bands) > 0 else 0
            eff_sparking = min(255, sparking + bass // 2)
            eff_cooling = max(60, cooling - bass // 6)

        # To conserve heat energy, diff_w + 2 should equal 32 (dw = 30)
        # Running the simulation `speed` times per frame animates the fire faster
        diff_w = 30
        self._ps_fire_inner(fire_rows, scale, eff_cooling, eff_sparking, diff_w, speed)

    @micropython.viper
    def _ps_fire_sim_viper(self, fh, ct, cols: int, fire_rows: int, cool_max: int, frame_off: int, eff_sparking: int, seed: int, diff_w: int) -> int:
        fh_ptr = ptr8(fh)
        ct_ptr = ptr8(ct)

        c: int = cols
        fr: int = fire_rows
        cm: int = cool_max
        fo: int = frame_off
        es: int = eff_sparking
        s: int = seed
        dw: int = diff_w

        n: int = fr * c
        rows_1: int = fr - 1

        # 1) Cool using precomputed table
        for i in range(n):
            v: int = int(fh_ptr[i]) - ((int(ct_ptr[(fo + i) & 63]) * cm) >> 8)
            if v < 0:
                v = 0
            fh_ptr[i] = v

        # 2) WLED vertical diffusion — dw controls rise speed (30=full, 4=very slow)
        for y in range(rows_1):
            b1: int = (y + 1) * c
            b2: int = (y + 2) * c
            if y + 2 >= fr:
                b2 = rows_1 * c
            y_cols: int = y * c
            for x in range(c):
                xl: int = x - 1
                if xl < 0:
                    xl = c - 1
                xr: int = x + 1
                if xr >= c:
                    xr = 0
                vert: int = (int(fh_ptr[b1 + x]) + (int(fh_ptr[b2 + x]) << 1)) // 3
                val: int = (vert * dw + int(fh_ptr[b1 + xl]) + int(fh_ptr[b1 + xr])) >> 5
                if val < 0:
                    val = 0
                fh_ptr[y_cols + x] = val

        # 3) Heat base & LCG sparking
        bottom: int = rows_1 * c
        for x in range(c):
            v_bottom: int = int(fh_ptr[bottom + x]) + 100
            if v_bottom > 255:
                v_bottom = 255
            fh_ptr[bottom + x] = v_bottom

            # Simple, fast LCG PRNG with small constants fitting inside small-integer types
            s = (s * 2053 + 13849) & 0xFFFF
            rand_val: int = s & 0xFF
            if rand_val < es:
                fh_ptr[bottom + x] = 255

        return s

    @micropython.viper
    def _ps_fire_render_viper(self, aled_buf, order_buf, fh, fire_idx, fire_rows: int, cols: int, scale: int):
        ab_ptr  = ptr8(aled_buf)
        o_ptr   = ptr8(order_buf)
        fh_ptr  = ptr8(fh)
        idx_ptr = ptr16(fire_idx)

        fr: int = fire_rows
        c: int = cols
        sc: int = scale

        ci: int = 0
        o0: int = int(o_ptr[0])
        o1: int = int(o_ptr[1])
        o2: int = int(o_ptr[2])

        for y in range(fr):
            row_base: int = y * c
            for x in range(c):
                h: int = int(fh_ptr[row_base + x])
                r: int = 0
                g: int = 0
                b: int = 0

                if h < 85:
                    r = h * 3
                elif h < 170:
                    r = 255
                    g = (h - 85) * 3
                else:
                    r = 255
                    g = 255
                    b = (h - 170) * 3

                # Write to raw buffer
                idx: int = int(idx_ptr[ci])
                ci += 1
                if idx >= 0:
                    base: int = idx * 3
                    ab_ptr[base + o0] = r
                    ab_ptr[base + o1] = g
                    ab_ptr[base + o2] = b

                if sc > 1:
                    idx = int(idx_ptr[ci])
                    ci += 1
                    if idx >= 0:
                        base = idx * 3
                        ab_ptr[base + o0] = r
                        ab_ptr[base + o1] = g
                        ab_ptr[base + o2] = b

                if sc > 2:
                    idx = int(idx_ptr[ci])
                    ci += 1
                    if idx >= 0:
                        base = idx * 3
                        ab_ptr[base + o0] = r
                        ab_ptr[base + o1] = g
                        ab_ptr[base + o2] = b

    def _ps_fire_inner(self, fire_rows, scale, eff_cooling, eff_sparking, diff_w=30, speed=1.0):
        cols = self.cols
        fh = self._fire_heat
        fs_data = self._fs_data
        fs_br = self._fs_br
        fs_x = self._fs_x

        rows_1 = fire_rows - 1

        # Accumulate speed to support sub-1.0 speeds smoothly
        if not hasattr(self, '_fire_accum'):
            self._fire_accum = 0.0
        self._fire_accum += float(speed)
        steps = int(self._fire_accum)
        self._fire_accum -= steps

        # cool_max scales with diff_w so flame height stays stable while speed changes
        ct = self._fire_cool_table
        frame_off = self._fire_frame
        base_cool = (eff_cooling * 10) // fire_rows + 2
        cool_max = max(1, base_cool * diff_w // 30)

        # 1) Physics Simulation (runs steps times)
        for _ in range(steps):
            self._fire_rand_seed = self._ps_fire_sim_viper(
                fh, ct, cols, fire_rows, cool_max, frame_off, eff_sparking, self._fire_rand_seed, diff_w
            )
            frame_off = (frame_off + 7) & 63
        self._fire_frame = frame_off

        # 2) Spark system (updates steps times to match physics speed)
        fs_count = self._fs_count
        for _ in range(steps):
            # Flame top: first row from y=0 with heat > 20
            flame_top_buf = rows_1
            for scan_y in range(fire_rows):
                row_base = scan_y * cols
                found = False
                for scan_x in range(cols):
                    if fh[row_base + scan_x] > 20:
                        found = True
                        break
                if found:
                    flame_top_buf = scan_y
                    break

            # Emit spark at 1/8 probability
            if fs_count < 15 and random.randint(0, 7) == 0 and flame_top_buf >= 4:
                sy_buf = flame_top_buf - random.randint(1, 3)
                vy_fp = -(3 + random.randint(0, 5))
                fs_data[fs_count * 2]     = sy_buf * 16
                fs_data[fs_count * 2 + 1] = vy_fp
                fs_br[fs_count]           = 230 + random.randint(0, 25)
                fs_x[fs_count]            = random.randint(0, cols - 1)
                fs_count += 1

            # Update sparks
            i = 0
            while i < fs_count:
                y_fp   = fs_data[i * 2] + fs_data[i * 2 + 1]
                new_br = fs_br[i] - 3
                if y_fp < 0 or new_br <= 0:
                    fs_count -= 1
                    if i < fs_count:
                        fs_data[i * 2]     = fs_data[fs_count * 2]
                        fs_data[i * 2 + 1] = fs_data[fs_count * 2 + 1]
                        fs_br[i]           = fs_br[fs_count]
                        fs_x[i]            = fs_x[fs_count]
                else:
                    fs_data[i * 2] = y_fp
                    fs_br[i]       = new_br
                    i += 1
        self._fs_count = fs_count

        # 3) Render once
        fire_idx = self._fire_idx
        gb = self.brightness
        aled = self.aled
        self._ps_fire_render_viper(
            aled.aled_buffer, aled._order_buf, fh, fire_idx, fire_rows, cols, scale
        )

        # Draw sparks: yellow-gold -> orange -> dark red -> black as they fade
        _set_rgb = aled._set_led_rgb
        for i in range(fs_count):
            sy = fs_data[i * 2] >> 4
            if 0 <= sy < fire_rows:
                sv = fs_br[i]
                # Quadratic green fade for beautiful cooling ember aesthetics
                sg = (sv * sv) // 384
                ci_s = sy * cols * scale + fs_x[i] * scale
                # Select only the middle physical pixel in the scaled row to remain exactly 1 pixel high
                idx = fire_idx[ci_s + (scale >> 1)]
                if idx >= 0: _set_rgb(idx, sv, sg, 0)

        aled.apply_brightness_to_buffer(gb)

    def render_fireworks(self, sparks_per_burst=14, gravity=3, min_interval=400,
                         audio_reactive=True):
        sparks_per_burst = int(sparks_per_burst)
        gravity = int(gravity)
        min_interval = int(min_interval)
        MAX = 60
        rows = self.rows
        cols = self.cols

        # Lazy init: _fire_particles packs [y_fp, vy_fp, heat] per spark (3 ints each)
        if self._fire_particles is None:
            self._fire_particles = array.array('i', [0] * (MAX * 3))
            self._fw_x = bytearray(MAX)
            self._fw_r = bytearray(MAX)
            self._fw_g = bytearray(MAX)
            self._fw_b = bytearray(MAX)
            self._fw_count = 0
            self._fw_last_burst = 0

        fp = self._fire_particles
        fx = self._fw_x
        fr = self._fw_r
        fg = self._fw_g
        fb = self._fw_b
        count = self._fw_count
        now = time.ticks_ms()
        is_active = self.c.mv_feat[51]
        bands = self.c.mv_bands

        # Fade previous frame
        self.aled.apply_brightness_to_buffer(210)

        # Decide whether to launch a new burst
        bass = bands[0] if (audio_reactive and is_active and len(bands) > 0) else 0
        elapsed = time.ticks_diff(now, self._fw_last_burst)
        trigger = False
        if audio_reactive:
            trigger = is_active and bass > 90 and elapsed > min_interval
        else:
            trigger = elapsed > min_interval * 2

        if trigger and count + sparks_per_burst <= MAX:
            self._fw_last_burst = now
            y0 = random.randint(rows // 5, (4 * rows) // 5)
            pal_idx = random.randint(0, self.pal_len - 1) if self.pal_len > 0 else 0
            pc = self._pal_color(pal_idx)
            pr = int(pc[0]); pg = int(pc[1]); pb_ = int(pc[2])
            n_sparks = min(sparks_per_burst, MAX - count)
            for _ in range(n_sparks):
                # velocity: -150..+150 fp-units/frame (fp=64 → max ±2.3 rows/frame)
                vy = random.randint(-150, 150)
                i = count
                fp[i * 3]     = y0 * 64
                fp[i * 3 + 1] = vy
                fp[i * 3 + 2] = 255
                fx[i] = random.randint(0, cols - 1)
                fr[i] = pr; fg[i] = pg; fb[i] = pb_
                count += 1

        # Update sparks and draw
        _get_idx = self._physical_index
        l_id = self.led_id
        gb = self.brightness
        i = 0
        while i < count:
            y_fp  = fp[i * 3]
            vy_fp = fp[i * 3 + 1]
            heat  = fp[i * 3 + 2]

            y_fp  += vy_fp
            vy_fp += gravity          # gravity pulls sparks downward
            heat  -= 5

            if heat <= 0 or y_fp < 0 or y_fp >= rows * 64:
                last = count - 1
                if i != last:
                    fp[i * 3]     = fp[last * 3]
                    fp[i * 3 + 1] = fp[last * 3 + 1]
                    fp[i * 3 + 2] = fp[last * 3 + 2]
                    fx[i] = fx[last]
                    fr[i] = fr[last]; fg[i] = fg[last]; fb[i] = fb[last]
                count -= 1
                continue

            fp[i * 3]     = y_fp
            fp[i * 3 + 1] = vy_fp
            fp[i * 3 + 2] = heat

            y = y_fp >> 6
            x = fx[i]
            idx = _get_idx(l_id, x, y)
            if idx >= 0:
                br = (gb * heat) >> 8
                self.aled[idx] = ((fr[i] * br) >> 8,
                                  (fg[i] * br) >> 8,
                                  (fb[i] * br) >> 8)
            i += 1

        self._fw_count = count

    def create_sections(self, sections):
        if isinstance(sections, str):
            if sections == 'rows':
                self.sections = [self.cols] * self.rows
            elif sections == 'cols':
                self.sections = [self.rows] * self.cols
            else:
                self.sections = [self.n_leds]
        elif isinstance(sections, int):
            if sections <= 0:
                sections = random.randint(1, self.n_leds)
            for s in range(sections, 0, -1):
                if self.n_leds % s == 0:
                    self.sections = [self.n_leds // s] * s
                    break
        elif isinstance(sections, (list, tuple)):
            self.sections = list(sections)
        else:
            self.sections = [self.n_leds]
        self.number_of_sections = len(self.sections)
        self.max_section_length = max(self.sections)

    def calculate_positions(self, section_no, section_length, section_start, effect_mode, offset, counter, direction):
        if section_length == self.n_leds:
            section_length -= 1

        pos1 = 0
        pos2 = None

        if effect_mode == 1:
            if direction == 1:
                pos1 = section_start + counter
            else:
                pos1 = section_start + (section_length - counter)
        elif effect_mode == 2:
            mid = (section_length + 1) // 2
            if direction == 1:
                pos1 = section_start + mid + counter
                pos2 = section_start + mid - counter
            else:
                pos1 = section_start + counter
                pos2 = section_start + (section_length - counter)
        elif effect_mode == 3:
            unoccupied = [i for i in range(section_start, section_start + section_length) if self._particle_status[i % self.n_leds] == 0]
            if unoccupied:
                pos1 = random.choice(unoccupied)
            else:
                return (None, None)

        pos1 = (pos1 + offset) % self.n_leds
        if pos2 is not None:
            pos2 = (pos2 + offset) % self.n_leds
        return (pos1, pos2)

    def calculate_multiplier(self, multiplier_method, length, x, counter, direction, t):
        if multiplier_method == 0:
            return random.random()
        if multiplier_method == 1:
            return 1.0
        if multiplier_method == 2:
            val = counter / length
            return val if direction == 1 else (1.0 - val)

        width = 0.0001
        if multiplier_method in (3, 6):
            width = random.randint(0, 10)
            if width < 2:
                width = random.random()
            if width == 0:
                width = 0.0001

        if multiplier_method == 3:
            return min(abs(min(sin(direction * width * x + 2.0 * t), 0.0)), 1.0)
        if multiplier_method == 4:
            return (sin(direction * 2.0 * x + t) + 1.0) / 2.0
        if multiplier_method == 5:
            return (max((1.0 + sin(pi / 2.0 + 4.0 * t)) ** 0.35, 1.0) - 1.0) * 4.0 % 1.0
        if multiplier_method == 6:
            return 0.5 + (sin(width * x) * cos(t)) / 2.0
        if multiplier_method == 7:
            return 0.5 + sin(floor(x + t)) / 2.0
        if multiplier_method == 10:
            if self._particle_status[x] != 0:
                val = self._particle_mult[x] - direction * 0.1
                return max(0.0, min(1.0, val))
        return 0.0

    def _update_sequence_from_particles(self, gamma=False, mode='B'):
        bpp = self.aled.bpp
        for i in range(self.n_leds):
            if self._particle_status[i] == 0:
                continue
            if mode == 'B':
                s_idx = i * bpp
                color = (self._particle_color[s_idx], self._particle_color[s_idx+1], self._particle_color[s_idx+2])
                color = self.color_multiply(color, self._particle_mult[i])
            elif mode == 'C':
                color = self._pal_color(int(self.pal_len * self._particle_mult[i]))
            elif mode == 'S':
                color = self.color_multiply(self.color_return('S', color_offset=i), self._particle_mult[i])
            self._set_led(i, color)

    def fade_effect(self, sections=None, color_p=(255,0,255), color_s=(0,0,0), color_t=(255,165,0), color_mode=0,
                    multiplier_mode=0, effect_mode=1, beginning_offset=0, delay=30, **kwargs):
        if self.fade_in is False and self.fade_out is False and self.sections is None:
            self.offset = beginning_offset % self.n_leds
            self.create_sections(sections)
            self.clear_particles()
            idx = 0
            for sec_idx, sec_len in enumerate(self.sections):
                for _ in range(sec_len):
                    if idx < self.n_leds:
                        self._particle_int0[idx] = sec_idx
                        idx += 1
            self.fade_in = True
            self.fade_out = False
            self.intermediate = False

        if self.fade_in and self.number_of_sections:
            t = time.ticks_ms() / 1000.0
            
            if isinstance(sections, int) and sections < 0:
                sec_idx = sections % self.number_of_sections
                sections_to_animate = [(sec_idx, self.sections[sec_idx], sum(self.sections[:sec_idx]))]
            else:
                sections_to_animate = []
                start = 0
                for i, sec_len in enumerate(self.sections):
                    sections_to_animate.append((i, sec_len, start))
                    start += sec_len

            for section_no, section_length, section_start in sections_to_animate:
                if effect_mode in (1, 3):
                    if self.counter >= section_length:
                        continue
                elif effect_mode == 2:
                    if self.counter > (section_length + 1) // 2:
                        continue

                positions = self.calculate_positions(section_no, section_length, section_start, effect_mode, self.offset, self.counter, self.direction)
                for pos in positions:
                    if pos is None:
                        continue
                    length = self.n_leds if multiplier_mode == 2 else section_length
                    multiplier = self.calculate_multiplier(multiplier_mode, length, pos, self.counter, self.direction, t)
                    color = self.color_from_colormode(color_p, color_s, color_t, color_mode, section_no, section_length, self.offset, self.counter, self.direction)
                    
                    self._particle_status[pos] = 1
                    self._particle_int0[pos] = section_no
                    self._particle_mult[pos] = multiplier
                    s_idx = pos * self.aled.bpp
                    self._particle_color[s_idx] = color[0]
                    self._particle_color[s_idx+1] = color[1]
                    self._particle_color[s_idx+2] = color[2]

            self.counter += self.step

        self._update_sequence_from_particles()
        self.update()

    def intermediate_effect(self, multiplier_mode, effect_mode, delay_intermediate):
        if self.fade_in is False and self.fade_out is False and self.sections and self.intermediate is True:
            if self.elapsed_time(self.last_time, delay_intermediate):
                self.last_time = time.ticks_ms()
                t = self.last_time / 1000.0
                if effect_mode == 1:
                    for i in range(self.n_leds):
                        if self._particle_status[i] != 0:
                            self._particle_mult[i] = self.calculate_multiplier(multiplier_mode, 1, i, self.counter, self.direction, t)
                elif effect_mode == 2:
                    for i in range(self.n_leds):
                        if self._particle_status[i] != 0 and self._particle_int0[i] % 2:
                            self._particle_mult[i] = self.calculate_multiplier(multiplier_mode, 1, i, self.counter, self.direction, t)

            self._update_sequence_from_particles()
            self.update()

    def mixer(self, sections=2, color_p=(255,255,255), color_s=(255,165,0), color_t=(128,0,128), color_mode=0, multiplier_mode=0,
              effect_mode=1, beginning_offset=0, delay_in=30, delay_intermediate=30, delay_out=30, wait_time=1000, random_cycle=False, **kwargs):
        if self.fade_in is False and self.fade_out is False and self.sections is None and self.elapsed_time(self.last_time, wait_time):
            if random_cycle:
                h1 = random.randint(0, 255)
                h2 = random.randint(0, 255)
                h3 = random.randint(0, 255)
                self._mixer_color_p = self._hsv_to_rgb(h1, 255, 255)
                self._mixer_color_s = self._hsv_to_rgb(h2, 255, 255)
                self._mixer_color_t = self._hsv_to_rgb(h3, 255, 255)
                self._mixer_sections = random.randint(2, 6)
                self._mixer_color_mode = random.randint(0, 4)
                self._mixer_multiplier_mode = random.randint(0, 2)
                self._mixer_effect_mode = random.randint(1, 3)
            else:
                self._mixer_color_p = color_p
                self._mixer_color_s = color_s
                self._mixer_color_t = color_t
                self._mixer_sections = sections
                self._mixer_color_mode = color_mode
                self._mixer_multiplier_mode = multiplier_mode
                self._mixer_effect_mode = effect_mode

            self.fade_effect(sections=self._mixer_sections, color_p=self._mixer_color_p, color_s=self._mixer_color_s, color_t=self._mixer_color_t,
                             color_mode=self._mixer_color_mode,
                             multiplier_mode=self._mixer_multiplier_mode, effect_mode=self._mixer_effect_mode,
                             beginning_offset=beginning_offset, delay=delay_in, **kwargs)
            self.intermediate = False
            self.fade_in = True
            self.last_time = time.ticks_ms()

        if self.fade_in is True and self.fade_out is False and self.intermediate is False and self.sections and self.elapsed_time(self.last_time, delay_in):
            self.fade_effect(sections=self._mixer_sections, color_p=self._mixer_color_p, color_s=self._mixer_color_s, color_t=self._mixer_color_t,
                             color_mode=self._mixer_color_mode,
                             multiplier_mode=self._mixer_multiplier_mode, effect_mode=self._mixer_effect_mode,
                             beginning_offset=beginning_offset, delay=delay_in, **kwargs)

            if self.counter > self.max_section_length:
                self.fade_in = False
                self.fade_out = False
                self.intermediate = True
                self.repeats = random.randint(60, 100)
                self.counter = 0

            self.last_time = time.ticks_ms()

        if self.fade_in is False and self.fade_out is False and self.intermediate is True and self.sections:
            self.intermediate_effect(multiplier_mode=self._mixer_multiplier_mode, effect_mode=self._mixer_effect_mode, delay_intermediate=delay_intermediate)
            self.repeats -= 1

            if self.repeats <= 0:
                self.fade_in = False
                self.intermediate = False
                self.fade_out = True
                self.counter = 0

        if self.fade_in is False and self.fade_out is True and self.sections:
            if self.elapsed_time(self.last_time, delay_out):
                still_active = False
                for i in range(self.n_leds):
                    if self._particle_status[i] != 0:
                        self._particle_mult[i] -= 0.1
                        if self._particle_mult[i] <= 0.0:
                            self._particle_mult[i] = 0.0
                            self._particle_status[i] = 0
                        else:
                            still_active = True

                self._update_sequence_from_particles()
                self.last_time = time.ticks_ms()

                if not still_active:
                    self.fade_out = False
                    self.counter = 0
                    if self.sections:
                        self.sections.clear()
                    self.sections = None

        self.update()

    def storm2(self, color_p=(255, 255, 255), color_s=(0, 0, 0), solid_color=True, **kwargs):
        if not hasattr(self, '_flash_brightness'):
            self._flash_brightness = 1.0

        if self.repeats == 0:
            if not self.elapsed_time(self.last_time, 600 * self.counter):
                return
            self.repeats = random.randint(1, 5)
            self.delay = random.randint(10, 35)
            self.counter = random.randint(1, 6)
            self.direction = 1
            self.clear_particles()

            _color = self.color_return(color_p)
            pc = self._particle_color
            bpp = self.aled.bpp
            is_rand = color_p in ('RM', 'R') and not solid_color
            rf = self.random_factor

            # Determine active LEDs for storm
            if self.rows == 5:
                active_indices = []
                for r in (2, 3):
                    for c in range(self.cols):
                        idx = self._physical_index(c, r)
                        if idx >= 0:
                            active_indices.append(idx)
            else:
                active_indices = range(self.n_leds)

            # Clear particle status and set color_s for all
            c_s = self.color_return(color_s)
            for i in range(self.n_leds):
                s_idx = i * bpp
                pc[s_idx] = c_s[0]
                pc[s_idx+1] = c_s[1]
                pc[s_idx+2] = c_s[2]

            # Populate target storm LEDs
            for i in active_indices:
                s_idx = i * bpp
                if rf(0.8):
                    if is_rand:
                        _color = self.color_return(color_p)
                    pc[s_idx] = _color[0]
                    pc[s_idx+1] = _color[1]
                    pc[s_idx+2] = _color[2]
                    self._particle_status[i] = 1

            self.last_time = time.ticks_ms()
            self.update()
            return

        bpp = self.aled.bpp
        if self.direction == 1:
            flash_duration = self.delay * self.counter
            if not self.elapsed_time(self.last_time, flash_duration):
                b = self._flash_brightness
                ps = self._particle_status
                pc = self._particle_color
                cm = self.color_multiply
                sp = self._set_led
                for i in range(self.n_leds):
                    if ps[i]:
                        s = i * bpp
                        sp(i, cm((pc[s], pc[s + 1], pc[s + 2]), b))
            else:
                lo = self.counter * 2
                self._flash_brightness = random.randint(min(lo, 100), 100) * 0.01
                self.direction = -1
                self.counter = random.randint(1, 6)
                self.last_time = time.ticks_ms()

        else:
            if not self.elapsed_time(self.last_time, self.delay * self.counter):
                self.clear_sequence(self.color_return(color_s))
            else:
                self.counter = random.randint(1, 6)
                self.direction = 1
                self.repeats -= 1
                lo = self.counter * 2
                self._flash_brightness = random.randint(min(lo, 100), 100) * 0.01
                self.last_time = time.ticks_ms()

        self.update()


    def rainbow_effect(self, delay=30, color_step=0, dynamic=True, self_direction_change=True, **kwargs):
        if isinstance(dynamic, str):
            dynamic = dynamic.lower() in ('true', '1', 'yes')
        else:
            dynamic = bool(dynamic)

        if self.elapsed_time(self.last_time, delay):
            self.counter += self.pal_step
            if not dynamic:
                color = self.color_return('R', color_step=color_step)
            else:
                self.calculate_pal_offset(color_step=color_step)
            
            n = self.n_leds
            step = self.pal_step
            direction = self.direction
            offset = self.pal_offset
            cr = self.color_return
            sp = self._set_led
            
            for i in range(n):
                if dynamic:
                    idx = (i * step) - (direction * offset)
                    sp(i, self._pal_color(idx))
                else:
                    sp(i, cr(color, color_step=color_step))
            self.last_time = time.ticks_ms()
            
        if self.counter >= self.pal_len and self_direction_change:
            self.direction_change()
            self.counter = 0
        self.update()

    def stars(self, delay=30, stars_quantity=10, color_p='R', color_s=(0,0,0), step=2, **kwargs):
        n = self.n_leds
        if stars_quantity > n:
            stars_quantity = n
        self._prepare_effect_arrays(stars_quantity, led='h', int0='h', int1='h', mult='f')
        
        limit = 256 if isinstance(color_p, tuple) else self.pal_len
        lower_limit = int(0.25 * limit)
        upper_limit = limit - lower_limit
        
        if self.elapsed_time(self.last_time, delay):
            if self.random_factor(0.85):
                if self._effect_count < stars_quantity:
                    led_number = random.randint(0, n - 1)
                    if self._occupied[led_number] == 0:
                        diff_factor = random.randint(-20, 20)
                        idx = self._effect_count
                        self._arr_led[idx] = led_number
                        self._arr_int0[idx] = 0
                        self._arr_int1[idx] = diff_factor
                        self._arr_mult[idx] = 0.0
                        self._occupied[led_number] = 1
                        self._effect_count += 1
            
            i = 0
            cr = self.color_return
            cm = self.color_multiply
            sp = self._set_led
            c_s = cr(color_s)
            is_r = color_p == 'R'
            
            while i < self._effect_count:
                mult = self._arr_mult[i]
                col_idx = self._arr_int0[i]
                diff = self._arr_int1[i]
                led = self._arr_led[i]
                
                if mult < 1.0 and col_idx < lower_limit:
                    mult += (1.0 / (lower_limit / step))
                    if mult > 1.0:
                        mult = 1.0
                elif col_idx >= upper_limit:
                    mult -= (1.0 / (lower_limit / step))
                    if mult <= 0.0:
                        mult = 0.0
                        
                col_idx += step
                self._arr_int0[i] = col_idx
                self._arr_mult[i] = mult
                
                if col_idx >= limit:
                    sp(led, c_s)
                    self._occupied[led] = 0
                    self._effect_swap_remove(i)
                else:
                    if is_r:
                        color = cr(color=col_idx, color_offset=diff)
                    else:
                        color = cr(color_p)
                    sp(led, cm(color, mult))
                    i += 1
            self.last_time = time.ticks_ms()
        self.update()

    def _update_comet_braid(self, idx, color_s):
        pos = self._arr_led[idx]
        p_len = self._arr_int1[idx]
        br_f1 = 1.0 / float(p_len) if p_len > 0 else 0.0
        br = 0.0
        dist = self._arr_int0[idx]
        direction = self._arr_int3[idx]
        steps = self._arr_int2[idx]
        collision = self._arr_int4[idx]
        sl = self.n_leds
        
        c_s = self.color_return(color_s)
        cm = self.color_multiply
        sp = self._set_led
        
        for d in range(p_len):
            position = (pos + direction * dist + direction * d) % sl
            pos_clear = (position + direction) % sl
            base_color = (self._arr_cr[idx], self._arr_cg[idx], self._arr_cb[idx])
            color = cm(base_color, (1.0 - br))
            if d == 1 and collision == 1:
                self._arr_cr[idx] = color[0]
                self._arr_cg[idx] = color[1]
                self._arr_cb[idx] = color[2]
            if steps < 2:
                color = c_s
            sp(position, color)
            sp(pos_clear, c_s)
            br += br_f1

    def _check_comet_collision(self, idx, color_mixing):
        sl = self.n_leds
        pos = self._arr_led[idx]
        direction = self._arr_int3[idx]
        dist = self._arr_int0[idx]
        pos1 = (pos + direction * dist) % sl
        color1 = (self._arr_cr[idx], self._arr_cg[idx], self._arr_cb[idx])
        
        for j in range(self._effect_count):
            if j == idx:
                continue
            pos2_led = self._arr_led[j]
            direction2 = self._arr_int3[j]
            dist2 = self._arr_int0[j]
            pos2 = (pos2_led + direction2 * dist2) % sl
            
            if abs(pos1 - pos2) < 1:
                self._arr_int4[idx] = 1
                self._arr_int4[j] = 1
                color2 = (self._arr_cr[j], self._arr_cg[j], self._arr_cb[j])
                if color_mixing == 'blend':
                    len1 = self._arr_int1[idx]
                    len2 = self._arr_int1[j]
                    total_len = len1 + len2
                    blend_factor = int((max(len1, len2) / total_len) * 255) if total_len > 0 else 127
                    color = self.color_blend(color1, color2, blend_factor)
                elif color_mixing == 'add':
                    color = self.color_add(color1, color2)
                else:
                    color = color1
                
                self._arr_cr[idx] = color[0]
                self._arr_cg[idx] = color[1]
                self._arr_cb[idx] = color[2]
                self._arr_cr[j] = color[0]
                self._arr_cg[j] = color[1]
                self._arr_cb[j] = color[2]
                break

    def comet(self, comets_quantity=0, braid_length=0, color_p=(255,255,255), color_s=(0,0,0), color_mixing='add', **kwargs):
        sl = self.n_leds
        max_comets = sl // 6
        if max_comets < 1:
            max_comets = 1
            
        if comets_quantity == 0:
            if self._effect_count == 0 and self.counter == 0:
                self.counter = random.randrange(1, max_comets + 1)
        else:
            self.counter = min(comets_quantity, max_comets)

        self._prepare_effect_arrays(self.counter, led='h', int0='h', int1='h', int2='h', int3='h', int4='h', mult='f', time='I', cr='B', cg='B', cb='B')

        if self.random_factor(0.75):
            if self._effect_count < self.counter:
                end_position = random.randrange(0, sl)
                if self._occupied[end_position] == 0:
                    if braid_length == 0:
                        _braid_length = random.randint(3, int(sl * 0.6 // self.counter)) if self.counter > 0 else 3
                    else:
                        _braid_length = braid_length
                    if _braid_length < 1:
                        _braid_length = 1
                    distance = random.randint(int(min(_braid_length * 1.5, sl)), sl)
                    direction = random.choice((-1, 1))
                    color = self.color_return(color_p)
                    delay = (random.randint(200, 350) // _braid_length)
                    idx = self._effect_count
                    self._arr_led[idx] = end_position
                    self._arr_int0[idx] = distance
                    self._arr_int1[idx] = _braid_length
                    self._arr_int2[idx] = _braid_length
                    self._arr_int3[idx] = direction
                    self._arr_int4[idx] = 0
                    self._arr_time[idx] = time.ticks_ms()
                    self._arr_cr[idx] = color[0]
                    self._arr_cg[idx] = color[1]
                    self._arr_cb[idx] = color[2]
                    self._arr_mult[idx] = float(delay)
                    self._occupied[end_position] = 1
                    self._effect_count += 1

        i = 0
        while i < self._effect_count:
            if self._arr_int2[i] <= 0:
                self._occupied[self._arr_led[i]] = 0
                self._effect_swap_remove(i)
            else:
                delay = self._arr_mult[i]
                if self._arr_int4[i] != 0:
                    delay *= 1.5
                if self.elapsed_time(self._arr_time[i], int(delay)):
                    self._update_comet_braid(i, color_s)
                    if self._arr_int0[i] > 0 and self._arr_int4[i] != 1:
                        self._check_comet_collision(i, color_mixing)
                        self._arr_int0[i] -= 1
                    elif (self._arr_int0[i] <= 0 or self._arr_int4[i] == 1) and self._arr_int2[i] >= 0:
                        self._arr_int2[i] -= 1
                    self._arr_time[i] = time.ticks_ms()
                i += 1

        self.update()

    def storm(self, color_p=(255, 255, 255), color_s=(0, 0, 0), solid_color=True, **kwargs):
        self.storm2(color_p, color_s, solid_color, **kwargs)

    def sparks(self, color_p='RM', rnd_fac=0.3, color_s=(0,0,0), **kwargs):
        self.clear_sequence(self.color_return(color_s))
        if self.random_factor(rnd_fac):
            position = random.randrange(0, self.n_leds)
            self._set_led(position, self.color_return(color_p))
        self.update()

    def magdalenas_lights(self, pause_time=120, wait_time=2000, color_p='RM', color_s=(0,0,0), **kwargs):
        self.delay = pause_time
        _color_p = self.color_return(color_p)
        _color_s = self.color_return(color_s)
        n = self.n_leds
        bpp = self.aled.bpp
        ps = self._particle_status
        pc = self._particle_color
        
        if self.direction == 1 and self.elapsed_time(self.last_time, pause_time):
            unoccupied = [i for i in range(n) if ps[i] == 0]
            if unoccupied:
                position = random.choice(unoccupied)
                ps[position] = 1
                s_idx = position * bpp
                pc[s_idx] = _color_p[0]
                pc[s_idx+1] = _color_p[1]
                pc[s_idx+2] = _color_p[2]
            self.last_time = time.ticks_ms()

        if self.direction == -1 and self.elapsed_time(self.last_time, pause_time):
            cnt = 0
            for i in range(n):
                if ps[i] == 1:
                    cnt += 1
            if cnt > 0:
                target = random.randint(0, cnt - 1)
                j = 0
                led = -1
                for i in range(n):
                    if ps[i] == 1:
                        if j == target:
                            led = i
                            break
                        j += 1
                if led >= 0:
                    ps[led] = 2
                    s_idx = led * bpp
                    pc[s_idx] = _color_s[0]
                    pc[s_idx+1] = _color_s[1]
                    pc[s_idx+2] = _color_s[2]
            self.last_time = time.ticks_ms()

        sp = self._set_led
        for i in range(n):
            status = ps[i]
            if status == 0:
                continue
            s_idx = i * bpp
            color = (pc[s_idx], pc[s_idx+1], pc[s_idx+2])
            sp(i, color)
            if status == 2:
                ps[i] = 0

        active_count = 0
        for i in range(n):
            if ps[i] != 0:
                active_count += 1

        if (active_count == n and self.direction == 1) or (active_count == 0 and self.direction == -1):
            self.direction_change()
            self.last_time = time.ticks_ms() + wait_time

        self.update()

    def bg_fire(self, intensity=150, cooling=55, sparking=120, delay=8, rows=None, cols=None, color_p=None, max_height=None, **kwargs):
        if self.elapsed_time(self.last_time, delay):
            c_val = cols if cols is not None else self.cols
            total_rows = rows if rows is not None else self.rows
            sim_rows = total_rows
            disp_rows = max_height if max_height is not None else (total_rows // 2)
            sl = sim_rows * c_val

            if self._fire_heat is None or len(self._fire_heat) != sl:
                self._fire_heat = bytearray(sl)
                gc.collect()

            if not hasattr(self, '_fire_heat_scaled') or self._fire_heat_scaled is None or len(self._fire_heat_scaled) != disp_rows * c_val:
                self._fire_heat_scaled = bytearray(disp_rows * c_val)
                gc.collect()

            fh = self._fire_heat
            cool_max = (cooling * 10) // sim_rows + 2
            cool_max_plus_1 = cool_max + 1
            
            # Using fast random getrandbits
            for i in range(sl):
                v = fh[i] - (random.getrandbits(9) % cool_max_plus_1)
                fh[i] = v if v > 0 else 0

            for r in range(sim_rows - 1):
                r_offset = r * c_val
                below_offset = r_offset + c_val
                b2_offset = below_offset + c_val
                if b2_offset + c_val <= sl:
                    for c in range(c_val):
                        fh[r_offset + c] = (fh[below_offset + c] + fh[b2_offset + c]) >> 1
                else:
                    for c in range(c_val):
                        b2 = b2_offset + c
                        fh[r_offset + c] = (fh[below_offset + c] + fh[b2 if b2 < sl else sl - 1]) >> 1

            if random.getrandbits(8) < sparking:
                c = random.getrandbits(9) % c_val
                idx = (sim_rows - 1) * c_val + c
                if idx < sl:
                    v = fh[idx] + (160 + (random.getrandbits(8) % 96))
                    fh[idx] = v if v < 256 else 255

            # Downscale simulated heat to visual rows
            fhs = self._fire_heat_scaled
            for i in range(disp_rows * c_val):
                fhs[i] = 0

            for r in range(sim_rows):
                r_offset = r * c_val
                y_phys = (sim_rows - 1 - r) * disp_rows // sim_rows
                phys_offset = y_phys * c_val
                for c in range(c_val):
                    h = fh[r_offset + c]
                    if h > fhs[phys_offset + c]:
                        fhs[phys_offset + c] = h

            base_color = self.color_return(color_p) if color_p else None
            
            get_index = self._physical_index
            led_id = self.led_id
            n_leds = self.n_leds
            aled = self.aled
            set_led_rgb = aled._set_led_rgb
            gb = self.brightness

            if base_color:
                r_color = base_color[0]
                g_color = base_color[1]
                b_color = base_color[2]
                for y in range(disp_rows):
                    y_offset = y * c_val
                    for c in range(c_val):
                        h = fhs[y_offset + c]
                        idx = get_index(led_id, c, y)
                        if idx >= 0 and idx < n_leds:
                            scale = (h * gb) >> 8
                            rr = (r_color * scale) >> 8
                            gg = (g_color * scale) >> 8
                            bb = (b_color * scale) >> 8
                            set_led_rgb(idx, rr, gg, bb)
            else:
                for y in range(disp_rows):
                    y_offset = y * c_val
                    for c in range(c_val):
                        h = fhs[y_offset + c]
                        if h < 85: 
                            r_c = h * 3
                            g_c = 0
                            b_c = 0
                        elif h < 170: 
                            r_c = 255
                            g_c = (h - 85) * 3
                            b_c = 0
                        else: 
                            r_c = 255
                            g_c = 255
                            b_c = (h - 170) * 3
                        
                        idx = get_index(led_id, c, y)
                        if idx >= 0 and idx < n_leds:
                            rr = (r_c * gb) >> 8
                            gg = (g_c * gb) >> 8
                            bb = (b_c * gb) >> 8
                            set_led_rgb(idx, rr, gg, bb)

            if disp_rows < total_rows:
                for r in range(disp_rows, total_rows):
                    for c in range(c_val):
                        idx = get_index(led_id, c, r)
                        if idx >= 0 and idx < n_leds:
                            set_led_rgb(idx, 0, 0, 0)

            self.last_time = time.ticks_ms()
        self.update()

    def render_motion_patterns(self, pattern='gradient', color_mode='complementary', 
                              motion='oscillate', speed=1.0, direction=1, 
                              segment_len=15, spacing=15, bg_brightness=0, 
                              audio_reactive=True, palette_shift_speed=0.5,
                              color1=None, color2=None):
        """
        Unified effect demonstrating Aleds methods:
        - aled_fast_fill (aleD_fast_fill)
        - _aled_fast_gradient_rgb (aled_fast_gradient_rgb)
        - _aled_fast_fill_segment_rgb (aled_fast_fill_segment_rgb)
        - apply_br_to_buffer
        - apply_br_per_pixel
        """
        now = time.ticks_ms()
        
        if not hasattr(self, '_motion_offset'):
            self._motion_offset = 0.0
            self._motion_hue = 0.0
            self._motion_vel_phase = 0.0
            self._motion_phase = 0.0
            self._motion_dir = 1
            self._motion_last_ms = now
            
        if not hasattr(self, '_chase_packets'):
            self._chase_packets = []
            self._last_beat_state = False
            
        if not hasattr(self, '_firefly_phase'):
            self._firefly_phase = 0.0
            
        dt = time.ticks_diff(now, self._motion_last_ms) / 1000.0
        if dt <= 0.0 or dt > 0.2:
            dt = 0.02
        self._motion_last_ms = now
        self._firefly_phase = (self._firefly_phase + dt * 1.5) % (2.0 * pi)
        
        is_active = self.c.mv_feat[51] if (hasattr(self.c, 'mv_feat') and len(self.c.mv_feat) > 51) else False
        
        # Check for beats (multi-layer: built-in, AGC bass_level, raw bass band, and transient flux/energy)
        beat_active = False
        if is_active:
            bands = self.c.mv_bands
            feat = self.c.mv_feat
            
            has_bands = (bands is not None and len(bands) > 0)
            has_feat = (feat is not None and len(feat) > 54)
            
            b_val = bands[0] if has_bands else 0
            b_level = feat[48] if has_feat else 0
            b_detector = (feat[44] == 1) if (feat is not None and len(feat) > 44) else False
            
            flux_level = feat[54] if has_feat else 0
            energy_level = feat[51] if has_feat else 0
            
            is_beat = b_detector or (b_level > 190) or (b_val > 85) or (flux_level > 200) or (energy_level > 220)
            
            # Debounce by state transition and minimum time elapsed (200ms)
            now_ms = time.ticks_ms()
            elapsed_beat = time.ticks_diff(now_ms, getattr(self, '_last_beat_ms', 0))
            
            if is_beat and not getattr(self, '_last_beat_state', False) and elapsed_beat > 200:
                beat_active = True
                self._last_beat_ms = now_ms
            self._last_beat_state = is_beat
        else:
            self._last_beat_state = False

        # Update existing beat-chase packets
        for pkt in self._chase_packets:
            pkt[0] += pkt[2] * dt
        self._chase_packets = [pkt for pkt in self._chase_packets if pkt[0] < self.n_leds + pkt[3]]
        
        if audio_reactive and is_active:
            bass = float(self.c.mv_feat[48])
            mid = float(self.c.mv_feat[49])
            high = float(self.c.mv_feat[50])
            bass_norm = bass / 255.0
            mid_norm = mid / 255.0
            high_norm = high / 255.0
            
            speed_mult = 0.5 + 1.5 * mid_norm
            hue_shift = (dt * palette_shift_speed * 20.0) * (1.0 + 3.0 * high_norm)
            target_brightness = int(self.brightness * (0.6 + 0.4 * bass_norm))
        else:
            speed_mult = 1.0
            hue_shift = dt * palette_shift_speed * 15.0
            target_brightness = self.brightness
            
        self._motion_hue = (self._motion_hue + hue_shift) % 256.0
        actual_speed = speed * speed_mult
        
        if motion == 'oscillate':
            self._motion_phase = (self._motion_phase + dt * actual_speed * 1.5) % (2.0 * pi)
            self._motion_offset = (self.n_leds / 2.0) + (self.n_leds / 2.0 - 5.0) * sin(self._motion_phase)
            
        elif motion == 'bounce':
            self._motion_vel_phase = (self._motion_vel_phase + dt * 1.2) % (2.0 * pi)
            speed_vel = (25.0 + 18.0 * sin(self._motion_vel_phase)) * actual_speed
            self._motion_offset += self._motion_dir * speed_vel * dt
            
            if self._motion_offset >= self.n_leds - 1:
                self._motion_offset = self.n_leds - 1
                self._motion_dir = -1
            elif self._motion_offset <= 0:
                self._motion_offset = 0
                self._motion_dir = 1
                
        elif motion == 'cruise':
            self._motion_vel_phase = (self._motion_vel_phase + dt * 1.8) % (2.0 * pi)
            speed_vel = (30.0 + 20.0 * sin(self._motion_vel_phase)) * actual_speed
            self._motion_offset = (self._motion_offset + direction * speed_vel * dt) % self.n_leds
            
        c1, c2 = self._resolve_motion_colors(color_mode, color1, color2, self._motion_hue)
        
        if beat_active and pattern == 'beat_chase':
            # Spawn a new packet!
            pkt_speed = (45.0 + (random.getrandbits(5) * 1.5)) * speed
            if pkt_speed < 10.0: pkt_speed = 35.0
            self._chase_packets.append([0.0, c1, pkt_speed, segment_len])
            
        if bg_brightness > 0 and pattern in ('segments', 'pixels', 'meteor', 'ping_pong', 'firefly', 'beat_chase'):
            bg_r = (c2[0] * bg_brightness) >> 8
            bg_g = (c2[1] * bg_brightness) >> 8
            bg_b = (c2[2] * bg_brightness) >> 8
            self.aled.fast_fill_segment(0, self.n_leds, (bg_r, bg_g, bg_b))
        else:
            self.aled.clear()
            
        if pattern == 'stripe':
            self.aled.fast_gradient(c1, c2)
            modulator = bytearray(self.n_leds)
            offset = self._motion_offset
            wave_len = segment_len if segment_len > 0 else 30
            for i in range(self.n_leds):
                angle = (i - offset) * 2.0 * pi / wave_len
                modulator[i] = int(127.5 + 127.5 * sin(angle))
                
            self.aled.apply_br_per_pixel(self.c.gamma_table, self.aled.aled_buffer, modulator)
            
        elif pattern == 'gradient':
            self.aled.fast_gradient(c1, c2)
            modulator = bytearray(self.n_leds)
            offset = self._motion_offset
            width = segment_len if segment_len > 0 else 20
            for i in range(self.n_leds):
                dist = abs(i - offset)
                if dist < width:
                    modulator[i] = int(255 * (0.5 + 0.5 * cos(pi * dist / width)))
                else:
                    modulator[i] = 0
            self.aled.apply_br_per_pixel(self.c.gamma_table, self.aled.aled_buffer, modulator)
            
        elif pattern == 'segments':
            period = segment_len + spacing
            if period <= 0: period = 10
            start_offset = int(self._motion_offset) % period
            
            for start_idx in range(-period, self.n_leds, period):
                s = start_idx + start_offset
                e = s + segment_len
                s_clipped = max(0, s)
                e_clipped = min(self.n_leds, e)
                if s_clipped < e_clipped:
                    self.aled.fast_fill_segment(
                        s_clipped, e_clipped,
                        (c1[0], c1[1], c1[2])
                    )
                    
        elif pattern == 'pixels':
            self.aled.fast_gradient(c1, c2)
            
            modulator = bytearray(self.n_leds)
            period = spacing if spacing > 0 else 15
            offset = self._motion_offset
            half_width = max(1.0, segment_len / 2.0)
            
            for i in range(self.n_leds):
                dist = abs((i - offset) % period)
                if dist > period / 2.0:
                    dist = period - dist
                    
                if dist < half_width:
                    factor = 1.0 - (dist / half_width)
                    modulator[i] = int(255 * factor * factor)
                else:
                    modulator[i] = 0
                    
            self.aled.apply_br_per_pixel(self.c.gamma_table, self.aled.aled_buffer, modulator)

        elif pattern == 'meteor':
            self.aled.fast_gradient(c1, c2)
            modulator = bytearray(self.n_leds)
            head = self._motion_offset
            travel_dir = self._motion_dir if motion == 'bounce' else (direction if motion == 'cruise' else 1)
            trail_len = segment_len if segment_len > 0 else 25
            
            for i in range(self.n_leds):
                diff = (head - i) * travel_dir
                if motion == 'cruise':
                    if diff < 0:
                        diff += self.n_leds
                    elif diff >= self.n_leds:
                        diff -= self.n_leds
                
                if diff == 0:
                    modulator[i] = 255
                elif 0 < diff < trail_len:
                    factor = 1.0 - (diff / trail_len)
                    modulator[i] = int(255 * factor * factor)
                else:
                    modulator[i] = 0
                    
            self.aled.apply_br_per_pixel(self.c.gamma_table, self.aled.aled_buffer, modulator)
            
        elif pattern == 'ping_pong':
            self.aled.fast_gradient(c1, c2)
            modulator = bytearray(self.n_leds)
            head1 = self._motion_offset
            head2 = self.n_leds - 1 - head1
            width = segment_len if segment_len > 0 else 15
            
            for i in range(self.n_leds):
                dist1 = abs(i - head1)
                val1 = 0
                if dist1 < width:
                    val1 = 255 * (0.5 + 0.5 * cos(pi * dist1 / width))
                    
                dist2 = abs(i - head2)
                val2 = 0
                if dist2 < width:
                    val2 = 255 * (0.5 + 0.5 * cos(pi * dist2 / width))
                    
                modulator[i] = min(255, int(val1 + val2))
                
            self.aled.apply_br_per_pixel(self.c.gamma_table, self.aled.aled_buffer, modulator)
            
        elif pattern == 'firefly':
            self.aled.fast_gradient(c1, c2)
            modulator = bytearray(self.n_leds)
            offset = self._motion_offset
            period = spacing if spacing > 0 else 20
            
            for i in range(self.n_leds):
                # Spatial angle along the strip
                spatial_angle = (i - offset) * 2.0 * pi / period
                # Decoupled slow breathing/blinking
                breathing = sin(spatial_angle + self._firefly_phase)
                val = breathing * cos(spatial_angle * 0.5 - self._firefly_phase * 0.7)
                if val > 0.5:
                    modulator[i] = int(255 * (val - 0.5) / 0.5)
                else:
                    modulator[i] = 0
                    
            self.aled.apply_br_per_pixel(self.c.gamma_table, self.aled.aled_buffer, modulator)

        elif pattern == 'beat_chase':
            # Renders each active traveling packet as a sharp glowing bead of 3-5 pixels
            # Overlapping beads additively blend their colors
            for pkt in self._chase_packets:
                center = int(pkt[0])
                col = pkt[1]
                
                # Draw center pixel (100% brightness)
                if 0 <= center < self.n_leds:
                    self.aled[center] = col
                    
                # Draw adjacent pixels at reduced brightness for a nice glow/softness
                glow1 = ((col[0] * 128) >> 8, (col[1] * 128) >> 8, (col[2] * 128) >> 8)
                glow2 = ((col[0] * 64) >> 8, (col[1] * 64) >> 8, (col[2] * 64) >> 8)
                
                # Left side
                if 0 <= center - 1 < self.n_leds:
                    c_exist = self.aled[center - 1]
                    self.aled[center - 1] = (min(255, c_exist[0] + glow1[0]), min(255, c_exist[1] + glow1[1]), min(255, c_exist[2] + glow1[2]))
                if 0 <= center - 2 < self.n_leds:
                    c_exist = self.aled[center - 2]
                    self.aled[center - 2] = (min(255, c_exist[0] + glow2[0]), min(255, c_exist[1] + glow2[1]), min(255, c_exist[2] + glow2[2]))
                    
                # Right side
                if 0 <= center + 1 < self.n_leds:
                    c_exist = self.aled[center + 1]
                    self.aled[center + 1] = (min(255, c_exist[0] + glow1[0]), min(255, c_exist[1] + glow1[1]), min(255, c_exist[2] + glow1[2]))
                if 0 <= center + 2 < self.n_leds:
                    c_exist = self.aled[center + 2]
                    self.aled[center + 2] = (min(255, c_exist[0] + glow2[0]), min(255, c_exist[1] + glow2[1]), min(255, c_exist[2] + glow2[2]))

        elif pattern == 'word_fill':
            # Dynamic 32-bit color pattern using aled_fast_fill!
            # Respects physical order of LEDs and introduces a black byte
            # spacer to preserve saturation and avoid white color wash-out
            offset_step = int(self._motion_offset) & 3
            
            # Reorder c1 to physical channel positions (GRB / RGB / BGR)
            o = self.aled._order_buf
            phys_c1 = [0, 0, 0]
            phys_c1[o[0]] = c1[0]
            phys_c1[o[1]] = c1[1]
            phys_c1[o[2]] = c1[2]
            
            # Build 4-byte sequence with a trailing zero (black)
            bytes_list = [phys_c1[0], phys_c1[1], phys_c1[2], 0]
            # Rotate by offset_step to animate motion
            bytes_list = bytes_list[offset_step:] + bytes_list[:offset_step]
            
            word_val = (bytes_list[0] << 24) | (bytes_list[1] << 16) | (bytes_list[2] << 8) | bytes_list[3]
            self.aled.aled_fast_fill(self.aled.aled_buffer, len(self.aled.aled_buffer) >> 2, word_val)
            
        target_brightness = max(0, min(255, target_brightness))
        self.aled.apply_br_to_buffer(self.c.gamma_table, target_brightness)

    # ------------------------------------------------------------------
    # STATIC 3-BAR DISPLAY  (non-audio, no motion)
    # ------------------------------------------------------------------


    def render_static_bars(self, start_positions=None, heights=None,
                           color_p=None, color_s=None, color_t=None, color_q=None,
                           columns=None, rainbow=False, color_mode=None,
                           target_brightness=255, auto_brightness=False,
                           color_interval_ms=0, height=None, pos=None,
                           hue_p=None, hue_s=None, hue_t=None, hue_q=None, **kwargs):
        """Static LED bars. Non-audio, no motion. Supports dynamic column sizes (3 or 4).

        color_p/s/t/q: explicit (R,G,B) tuple, string ('R', 'RM'), or None to pick from palette.
        rainbow=True : gradient along each bar from palette.
        color_mode: string (e.g. 'sunset', 'neon', 'ocean') to use harmonized palette types.
        target_brightness: override brightness level (0-255).
        auto_brightness: True to read from light sensor (lux) to scale brightness automatically.
        color_interval_ms: millisecond interval to wait before picking new colors (e.g. 1000 for slow RM).
        """
        self.aled.clear()

        rows  = self.rows
        cols  = self.cols
        
        if auto_brightness:
            gb = self.c.process_lux(self.c.lux)
        elif target_brightness != 255:
            gb = target_brightness
        else:
            gb = self.brightness

        pal_n = self.pal_len
        bpp   = self.aled.bpp
        pal   = self.c.palette

        if columns is None:
            columns = tuple(range(cols))
        else:
            columns = tuple(columns)

        num_bars = len(columns)

        if start_positions is None:
            start_positions = (rows - 1,) * num_bars
        else:
            start_positions = tuple(start_positions)
            if len(start_positions) < num_bars:
                start_positions = start_positions + (rows - 1,) * (num_bars - len(start_positions))

        if heights is None:
            heights = (-rows,) * num_bars
        else:
            heights = tuple(heights)
            if len(heights) < num_bars:
                heights = heights + (-rows,) * (num_bars - len(heights))

        # 1. Store base default values of first bar to detect general shift relative to them
        default_pos_0 = start_positions[0] if len(start_positions) > 0 else 137
        default_h_0 = heights[0] if len(heights) > 0 else -138

        # 2. Check for individual column overrides in kwargs (e.g. pos_0, pos_1, pos_2, pos_3)
        start_positions = list(start_positions)
        for i in range(num_bars):
            key = f"pos_{i}"
            if key in kwargs and kwargs[key] is not None:
                start_positions[i] = kwargs[key]
        start_positions = tuple(start_positions)

        # Check for individual column overrides in kwargs (e.g. height_0, height_1, height_2, height_3)
        heights = list(heights)
        for i in range(num_bars):
            key = f"height_{i}"
            if key in kwargs and kwargs[key] is not None:
                heights[i] = kwargs[key]
        heights = tuple(heights)

        # 3. Apply general 'pos' shift relative to default_pos_0
        if pos is not None and pos != default_pos_0 and len(start_positions) > 0:
            diff = pos - default_pos_0
            start_positions = tuple(max(0, min(rows - 1, p + diff)) for p in start_positions)

        # Apply general 'height' shift relative to default_h_0
        if height is not None and height != default_h_0 and len(heights) > 0:
            diff = height - default_h_0
            new_heights = []
            for h in heights:
                new_val = h + diff
                if h >= 0:
                    new_val = max(0, new_val)
                else:
                    new_val = min(0, new_val)
                new_heights.append(new_val)
            heights = tuple(new_heights)

        # Pre-resolve solid colors using color_mode or color_return
        now = time.ticks_ms()
        sig_p = tuple(color_p) if isinstance(color_p, (list, tuple)) else color_p
        sig_s = tuple(color_s) if isinstance(color_s, (list, tuple)) else color_s
        sig_t = tuple(color_t) if isinstance(color_t, (list, tuple)) else color_t
        sig_q = tuple(color_q) if isinstance(color_q, (list, tuple)) else color_q
        sig = (sig_p, sig_s, sig_t, sig_q, color_mode, color_interval_ms, num_bars, hue_p, hue_s, hue_t, hue_q)
        
        use_cache = False

        if color_interval_ms > 0 and hasattr(self, '_sb_sig') and self._sb_sig == sig:
            if time.ticks_diff(now, self._sb_last_tick) < color_interval_ms:
                use_cache = True

        if use_cache:
            solid = self._sb_solid
        else:
            self._sb_sig = sig
            self._sb_last_tick = now

            solid = []
            if color_mode is not None:
                primary_color = self.color_return(color_p if color_p is not None else 0)
                base_hue, _, _ = self._rgb_to_hsv(primary_color[0], primary_color[1], primary_color[2])

                for i in range(num_bars):
                    if color_mode == 'complementary':
                        hue = (base_hue + (128 if i % 2 == 1 else 0)) % 256
                        solid.append(self._hsv_to_rgb(hue, 255, 255))
                    elif color_mode == 'triadic':
                        hue = (base_hue + (i * 85)) % 256
                        solid.append(self._hsv_to_rgb(hue, 255, 255))
                    elif color_mode in ('similar', 'analogous'):
                        diff = 20 * ((i + 1) // 2) * (1 if i % 2 == 1 else -1)
                        hue = (base_hue + diff) % 256
                        solid.append(self._hsv_to_rgb(hue, 255, 255))
                    elif color_mode == 'monochromatic':
                        sat = 255 - (i * 64) % 128
                        val = 255 - (i * 64) % 128
                        solid.append(self._hsv_to_rgb(base_hue, sat, val))
                    else:
                        # sunset, neon, ocean, etc.
                        hue_offset = (base_hue + i * 85) % 256
                        _, col = self._get_harmonized_colors(color_mode, hue_offset)
                        solid.append(col)
            else:
                for i in range(num_bars):
                    if i == 0:
                        color_val = color_p if color_p is not None else 0
                    elif i == 1:
                        color_val = color_s if color_s is not None else pal_n // 4
                    elif i == 2:
                        color_val = color_t if color_t is not None else 2 * pal_n // 4
                    elif i == 3:
                        color_val = color_q if color_q is not None else 3 * pal_n // 4
                    else:
                        color_val = (i * pal_n // num_bars)
                    solid.append(self.color_return(color_val))

            # Helper to adjust color hue while preserving saturation and value
            def adjust_color_hue(color, new_hue):
                if color is None or new_hue is None or new_hue == -1:
                    return color
                if isinstance(color, str):
                    return color
                r, g, b = color
                h, s, v = self._rgb_to_hsv(r, g, b)
                if new_hue != h:
                    return self._hsv_to_rgb(new_hue, s, v)
                return color

            # Apply hue overrides if they differ from the original colors' hues
            if len(solid) > 0 and hue_p is not None:
                solid[0] = adjust_color_hue(solid[0], hue_p)
            if len(solid) > 1 and hue_s is not None:
                solid[1] = adjust_color_hue(solid[1], hue_s)
            if len(solid) > 2 and hue_t is not None:
                solid[2] = adjust_color_hue(solid[2], hue_t)
            if len(solid) > 3 and hue_q is not None:
                solid[3] = adjust_color_hue(solid[3], hue_q)

            self._sb_solid = solid

        scaled_solid = []
        for col in solid:
            if gb != 255:
                scaled_solid.append(self.aled.change_brightness(col, gb))
            else:
                scaled_solid.append(col)

        if not hasattr(self, '_sb_scroll_offset'):
            self._sb_scroll_offset = 0
            self._sb_last_scroll_tick = now

        # Calculate how many scroll steps should occur based on color_interval_ms
        interval = max(1, color_interval_ms)
        elapsed_scroll = time.ticks_diff(now, self._sb_last_scroll_tick)
        if elapsed_scroll < 0 or elapsed_scroll > 10000:
            elapsed_scroll = interval
            self._sb_last_scroll_tick = now

        if elapsed_scroll >= interval:
            steps = elapsed_scroll // interval
            self._sb_scroll_offset = (self._sb_scroll_offset + steps) % pal_n
            self._sb_last_scroll_tick = time.ticks_add(self._sb_last_scroll_tick, steps * interval)

        for i in range(num_bars):
            x = columns[i]
            if x < 0 or x >= cols:
                continue

            y0 = min(rows - 1, max(0, start_positions[i]))
            h_raw = heights[i]
            h_abs = abs(h_raw)
            if h_abs <= 0:
                continue

            step_y = 1 if h_raw >= 0 else -1

            if step_y == 1:
                h = min(rows - y0, h_abs)
            else:
                h = min(y0 + 1, h_abs)

            if h <= 0:
                continue

            # Get specific color value for this column
            if i == 0:
                col_val = color_p
            elif i == 1:
                col_val = color_s
            elif i == 2:
                col_val = color_t
            elif i == 3:
                col_val = color_q
            else:
                col_val = None

            if col_val == "RG" or (i == 0 and (rainbow or color_mode == 'rainbow')):
                # Scrolling gradient rainbow along this column
                bar_off = (self._sb_scroll_offset + i * pal_n // num_bars) % pal_n
                for r in range(h):
                    y = y0 + r * step_y
                    if y < 0 or y >= rows: break
                    idx = self._physical_index(x, y)
                    if idx >= 0:
                        color_idx = (bar_off + r * pal_n // h) % pal_n
                        offset = color_idx * bpp
                        c = (pal[offset], pal[offset + 1], pal[offset + 2])
                        if gb != 255:
                            c = self.aled.change_brightness(c, gb)
                        self.aled[idx] = c
            elif col_val == "R":
                # Cycling rainbow (entire column has same color, shifting over time)
                color_idx = (self._sb_scroll_offset + i * pal_n // num_bars) % pal_n
                offset = color_idx * bpp
                col = (pal[offset], pal[offset + 1], pal[offset + 2])
                if gb != 255:
                    col = self.aled.change_brightness(col, gb)
                for r in range(h):
                    y = y0 + r * step_y
                    if y < 0 or y >= rows: break
                    idx = self._physical_index(x, y)
                    if idx >= 0:
                        self.aled[idx] = col
            else:
                col = scaled_solid[i]
                for r in range(h):
                    y = y0 + r * step_y
                    if y < 0 or y >= rows: break
                    idx = self._physical_index(x, y)
                    if idx >= 0:
                        self.aled[idx] = col






    def render_auto(self):
        """Intelligent effect router - picks the best visualizer for current audio."""
        if not self._check_active(clear=False):
            return
        mv = self.c.mv_feat
        bass_n = mv[48] / 255.0
        mid_n = mv[49] / 255.0
        treble_n = mv[50] / 255.0
        if treble_n > 0.75 and mid_n > 0.5:
            self.render_quantum_rift()
        elif bass_n > 0.8:
            self.render_tunnel()
        elif bass_n > 0.5 and treble_n > 0.4:
            self.render_ps_fire(audio_reactive=True)
        elif mid_n > 0.6:
            self.render_gravity_well()
        elif treble_n > 0.5:
            self.render_sparkles()
        elif bass_n > 0.3:
            self.render_wave_audio()
        else:
            self.render_classic(direction='bottom-up', max_height=self.rows, show_peaks=True)


    def render_beat_flash(self, threshold=0.6):
        """Palette shift on bass, spots on mid, jitter on treble."""
        if not self._check_active(clear=False):
            return
        self.aled.apply_brightness_to_buffer(int(0.82 * 255))
        mv = self.c.mv_feat

        # Software envelope tracking for adaptive beat detection
        if not hasattr(self, '_bf_avg_bass'):
            self._bf_avg_bass = 80.0
            self._bf_avg_mid = 80.0
            self._bf_avg_treble = 80.0

        self._bf_avg_bass = self._bf_avg_bass * 0.97 + mv[48] * 0.03
        self._bf_avg_mid = self._bf_avg_mid * 0.97 + mv[49] * 0.03
        self._bf_avg_treble = self._bf_avg_treble * 0.97 + mv[50] * 0.03

        is_bass = (mv[48] > self._bf_avg_bass * 1.25 and mv[48] > 10) or (mv[48] > 200)
        is_mid = (mv[49] > self._bf_avg_mid * 1.25 and mv[49] > 10) or (mv[49] > 200)
        is_treble = (mv[50] > self._bf_avg_treble * 1.25 and mv[50] > 10) or (mv[50] > 200)

        if is_bass:
            if not hasattr(self, '_bf_flash_color'):
                self._bf_flash_color = 0
            self._bf_flash_color = (self._bf_flash_color + 32) % max(1, self.pal_len)
            if random.random() < 0.5:
                color = self._pal_color(self._bf_flash_color)
                for i in range(self.n_leds):
                    self._set_led(i, color, 90)
        if is_mid:
            for _ in range(3):
                idx = random.randint(0, self.n_leds - 1)
                self._set_led(idx, self._pal_color(random.randint(0, self.pal_len - 1)), 200)
        if is_treble:
            for _ in range(2):
                idx = random.randint(0, self.n_leds - 1)
                self._set_led(idx, (255, 255, 255), 255)


    def render_beat_impact(self):
        """Full-grid flash on beat; brightness = beat_strength, hue from dominant band."""
        if not self._check_active(clear=False): return
        self.aled.apply_brightness_to_buffer(int(0.84 * 255))
        mv = self.c.mv_feat

        # Software fallback beat detection
        if not hasattr(self, '_bi_avg_energy'):
            self._bi_avg_energy = 80.0
            self._bi_last_trigger = 0

        current_energy = mv[51]
        self._bi_avg_energy = self._bi_avg_energy * 0.97 + current_energy * 0.03

        now = time.ticks_ms()
        software_beat = False
        if current_energy > self._bi_avg_energy * 1.25 and current_energy > 8:
            if time.ticks_diff(now, self._bi_last_trigger) > 200:
                software_beat = True
                self._bi_last_trigger = now

        # Trigger on either hardware or software beat detection
        if not (mv[44] or software_beat):
            return

        strength = mv[45] if mv[44] else int(current_energy)
        if strength < 2: 
            return

        bass = mv[48]; mid = mv[49]; treble = mv[50]
        hue_int = 0 if (bass >= mid and bass >= treble) else (120 if mid >= treble else 240)
        pal = self.c.palette
        pal_len = self.c.pal_length
        gb = self.brightness

        pi = (hue_int * pal_len // 360) * 3
        # Direct flash on the hardware object
        rr, gg, bb = self._pal_rgb(pi, strength, gb)

        if rr < 2 and gg < 2 and bb < 2: return
        self.aled.aled_fill((rr, gg, bb))


    def render_blocks(self, threshold=0.6):
        """Floor/ceiling blocks reactive to frequency hits."""

        features = self._check_active()
        if features is None:
            return
        mv = self.c.mv_feat
        b_amp = self._smooth_bar(0, float(mv[48])) / 255.0
        m_amp = self._smooth_bar(1, float(mv[49])) / 255.0
        floor_h = int(b_amp * (self.rows // 2))
        ceil_h = int(m_amp * (self.rows // 2))
        t = time.ticks_ms() / 1000.0
        for r in range(floor_h):
            color = self._pal_color(int(t * 10) % max(1, self.pal_len))
            for c in range(self.cols):
                idx = self._physical_index(c, r)
                if 0 <= idx < self.n_leds:
                    self._set_led(idx, color, 163)
        for r in range(self.rows - ceil_h, self.rows):
            color = self._pal_color(int(t * 10 + 128) % max(1, self.pal_len))
            for c in range(self.cols):
                idx = self._physical_index(c, r)
                if 0 <= idx < self.n_leds:
                    self._set_led(idx, color, 163)



    def render_bpm_pulse(self):
        """Hue cycles at bpm_est rate; beat_strength flashes complement color."""
        if not self._check_active(): return
        gb = self.brightness
        mv = self.c.mv_feat
        pal = self.c.palette
        pal_len = self.c.pal_length
        buf = self.buffer
        o0 = self.order0; o1 = self.order1; o2 = self.order2
        rows = self.rows; cols = self.cols
        rows_m1 = max(1, rows - 1)
        energy = mv[51]; bpm = mv[46]; beat = mv[44]; beat_str = mv[45]
        t_ms = time.ticks_ms()
        if bpm > 0:
            period_ms = max(1, 60000 // bpm)
            hue_base = (t_ms % period_ms) * 360 // period_ms
        else:
            hue_base = (t_ms % 2000) * 360 // 2000
        c = self.c
        for row in range(rows):
            t256 = row * 256 // rows_m1
            hue_int = (hue_base + (t256 * 60) // 256) % 360
            pi = hue_int * pal_len // 360 * 3
            val = (energy * (77 + ((179 * t256) >> 8))) >> 8
            rr, gg, bb = self._pal_rgb(pi, val, gb)
            for col in range(cols):
                idx = self._physical_index(col, row)
                pos = idx * 3
                buf[pos+o0] = rr; buf[pos+o1] = gg; buf[pos+o2] = bb
        if beat and beat_str > 38:
            flash_hue = (hue_base + 180) % 360
            pi = flash_hue * pal_len // 360 * 3
            fr = (pal[pi] * 77 >> 8) + 178; fg = (pal[pi+1] * 77 >> 8) + 178; fb = (pal[pi+2] * 77 >> 8) + 178
            if fr > 255: fr = 255
            if fg > 255: fg = 255
            if fb > 255: fb = 255
            fv = beat_str * 30 >> 8
            rr = (fr * fv) >> 8; rr = (rr * gb) >> 8
            gg = (fg * fv) >> 8; gg = (gg * gb) >> 8
            bb = (fb * fv) >> 8; bb = (bb * gb) >> 8
            self.aled.aled_fill((rr, gg, bb))


    def render_fast_bars(self, scale=8):
        """Direct bass/mid/treble bars — no smoothing."""
        mv = self.c.mv_feat
        self.aled.clear()
        if mv[51] < 12:
            return
        buf = self.buffer; gb = self.brightness; pal = self.palette; pal_len = self.pal_len
        if not pal_len:
            return
        o0 = self.order0; o1 = self.order1; o2 = self.order2
        rows = self.rows; cols = self.cols; n_leds = self.n_leds; idx_map = self._idx_map
        for col in range(min(cols, 3)):
            level = mv[48 + col]
            fill = level * rows * scale >> 11
            if fill > rows: fill = rows
            pi = (col * 120) * pal_len // 360 * 3
            for row in range(fill):
                brightness = 128 + row * 127 // max(1, rows)  # 128-255 gradient
                rr, gg, bb = self._pal_rgb(pi, brightness, gb)
                idx = idx_map[row * cols + col]
                if 0 <= idx < n_leds:
                    p = idx * 3
                    buf[p+o0] = rr; buf[p+o1] = gg; buf[p+o2] = bb


    def render_fire_ice(self, max_height=90, start_row=0, **kwargs):
        """Redirect to Particle System Fire (render_ps_fire) for backward compatibility."""
        self.render_ps_fire(audio_reactive=True, **kwargs)


    def render_flux_onset(self, threshold=1.2, **kwargs):
        """Spectral flux drives a vertical burst on transients."""
        if not self._check_active(clear=False): return
        self.aled.apply_brightness_to_buffer(int(0.85 * 255))
        mv = self.c.mv_feat
        flux = mv[54]; beat = mv[44]
        if flux < int(26 * threshold) and not beat: return
        gb = self.brightness
        pal = self.c.palette
        pal_len = self.c.pal_length
        buf = self.buffer
        o0 = self.order0; o1 = self.order1; o2 = self.order2
        rows = self.rows; cols = self.cols
        rows_m1 = max(1, rows - 1)
        hue_base = mv[53] * 240 // 255
        intensity = flux * 2 + (128 if beat else 0)
        if intensity > 255: intensity = 255
        c = self.c
        for row in range(rows):
            t256 = row * 256 // rows_m1
            tent = 128 - abs(t256 - 128)
            if tent < 0: tent = 0
            fade = (intensity * tent) >> 7
            if fade < 13: continue
            hue_int = (hue_base + (t256 * 60) // 256) % 360
            pi = hue_int * pal_len // 360 * 3
            rr, gg, bb = self._pal_rgb(pi, fade, gb)
            for col in range(cols):
                idx = self._physical_index(col, row)
                if 0 <= idx < self.n_leds:
                    pos = idx * 3
                    buf[pos+o0] = rr; buf[pos+o1] = gg; buf[pos+o2] = bb


    def render_gravity_bounce(self):
        """Gravity bounce columns with horizontal swerve and wall reflection."""
        if not self._check_active():
            return

        mv = self.c.mv_feat
        bass = float(mv[48])
        high = float(mv[50])
        bass_norm = self._norm(bass)
        high_norm = self._norm(high)
        activity = max(bass_norm, high_norm)
        active = bass > self.noise_threshold * 0.6 or high > self.noise_threshold * 0.6

        pool = self._ensure_bounce_pool()
        max_balls = len(pool)
        rows = self.rows
        cols = max(2, self.cols)
        idx_map = self._idx_map
        n_leds = self.n_leds
        spectrum_palette = self.spectrum_palette

        if active and self._bounce_count < max_balls:
            spawn_prob = 0.06 + activity * 0.24
            spawn_attempts = 1 + int(activity * 3.0)
            for _ in range(spawn_attempts):
                if self._bounce_count >= max_balls:
                    break
                if random.random() < spawn_prob:
                    col = random.uniform(0.0, float(cols - 1) * 0.7) if cols > 1 else 0.0
                    vel_x = random.uniform(0.08, 0.22) if cols > 1 else 0.0
                    color_pick = (int(col) * 4 + int((bass_norm + high_norm) * 6.0) + random.randint(0, 2)) % 12
                    slot = pool[self._bounce_count]
                    slot[0] = float(rows - 1)
                    slot[1] = col
                    slot[2] = vel_x
                    slot[3] = 0.0
                    slot[4] = color_pick
                    slot[5] = 1.0
                    slot[6] = 0
                    self._bounce_count += 1

        g = (0.07 + bass_norm * 0.18) * 0.40
        write_idx = 0
        count = self._bounce_count
        for read_idx in range(count):
            ball = pool[read_idx]
            row, col, vel_x, vel_y, color_pick, life, rest_hits = ball
            vel_y -= g
            row += vel_y * 0.6
            col += vel_x * 0.6

            # Floor bounce
            if row <= 0:
                row = 0.0
                restitution = 0.50 + high_norm * 0.28
                vel_y = abs(vel_y) * restitution
                vel_y += bass_norm * 0.15
                if abs(vel_y) < 0.16:
                    rest_hits += 1
                else:
                    rest_hits = 0

            # Side bounce
            if col < 0:
                col = 0.0
                vel_x = -vel_x * 0.8
            elif col > cols - 1:
                col = float(cols - 1)
                vel_x = -vel_x * 0.8

            # Lifetime drains steadily and faster on silence.
            life -= (0.010 + (0.020 if not active else 0.0))
            if rest_hits >= 4:
                life -= 0.20

            moving = abs(vel_y) > 0.05 or row > 0
            if life > 0.0 and (moving or rest_hits < 4):
                ball[0], ball[1], ball[2], ball[3], ball[5], ball[6] = row, col, vel_x, vel_y, life, rest_hits
                if write_idx != read_idx:
                    pool[write_idx], pool[read_idx] = pool[read_idx], pool[write_idx]
                write_idx += 1
                
                i_row = int(row)
                i_col = int(col)
                color = spectrum_palette[color_pick]
                main_b = min(1.0, (0.45 + activity * 0.45) * life)
                if 0 <= i_row < rows and 0 <= i_col < cols:
                    idx = idx_map[i_row * cols + i_col]
                    if 0 <= idx < n_leds:
                        self._set_led(idx, color, int(main_b * 255))
                    trail_row = i_row + 1
                    if trail_row < rows:
                        idx2 = idx_map[trail_row * cols + i_col]
                        if 0 <= idx2 < n_leds:
                            self._set_led(idx2, color, int((main_b * (0.35 + high_norm * 0.2)) * 255))
        self._bounce_count = write_idx


    def render_gravity_well(self):
        """High-contrast vortex well with stronger motion and palette-driven color."""
        if not self._check_active():
            return

        mv = self.c.mv_feat
        bass, mid, high = float(mv[48]), float(mv[49]), float(mv[50])
        bass_norm = self._norm(bass)
        mid_norm = self._norm(mid)
        high_norm = self._norm(high)
        activity = max(bass_norm, mid_norm, high_norm)
        active = bass > self.noise_threshold * 0.65 or mid > self.noise_threshold * 0.65

        pool = self._ensure_grav_pool()
        rows = self.rows
        cols = self.cols
        idx_map = self._idx_map
        n_leds = self.n_leds
        spectrum_palette = self.spectrum_palette
        pal_len = self.pal_len
        palette = self.palette

        # On silence: fade quickly and keep CPU work minimal.
        if not active:
            write_idx = 0
            count = self._grav_count
            for read_idx in range(count):
                p = pool[read_idx]
                p[4] -= 0.12
                if p[4] > 0:
                    if write_idx != read_idx:
                        pool[write_idx], pool[read_idx] = pool[read_idx], pool[write_idx]
                    write_idx += 1
            self._grav_count = write_idx
            return

        t = time.ticks_ms() / 1000.0
        c_row = (rows * 0.50) + sin(t * (0.55 + mid_norm * 1.4)) * (rows * 0.14)
        c_col = (cols * 0.5) + cos(t * (0.45 + high_norm * 1.2)) * 0.25

        max_particles = len(pool)
        spawn = int(2 + bass_norm * 7 + mid_norm * 5 + high_norm * 3)
        free_slots = max_particles - self._grav_count
        if free_slots <= 0:
            spawn = 0
        elif spawn > free_slots:
            spawn = free_slots

        for _ in range(spawn):
            edge = random.randint(0, 3)
            if edge == 0:
                row, col = 0.0, random.randint(0, cols - 1)
            elif edge == 1:
                row, col = float(rows - 1), random.randint(0, cols - 1)
            elif edge == 2:
                row, col = random.randint(0, rows - 1), 0.0
            else:
                row, col = random.randint(0, rows - 1), float(cols - 1)

            if pal_len > 0 and palette:
                color_pick = int(random.random() * pal_len)
            else:
                color_pick = int(random.random() * 12)
            if self._grav_count < max_particles:
                slot = pool[self._grav_count]
                slot[0] = float(row)
                slot[1] = float(col)
                slot[2] = 0.0
                slot[3] = 0.0
                slot[4] = 1.0
                slot[5] = color_pick
                self._grav_count += 1

        # In-place compaction: avoids allocating new list every frame.
        write_idx = 0
        count = self._grav_count
        for read_idx in range(count):
            p = pool[read_idx]
            row, col, vr, vc, life, color_pick = p
            dr = c_row - row
            dc = c_col - col
            d2 = dr * dr + dc * dc
            if d2 < 0.04:
                d2 = 0.04
            dist = sqrt(d2)
            inv_d = 1.0 / dist

            # Stronger gravity + swirl for a more visible vortex.
            pull = (0.022 + bass_norm * 0.14 + mid_norm * 0.08) * 0.40
            swirl = (0.014 + high_norm * 0.07 + mid_norm * 0.03) * 0.40
            pulse = 1.0 + bass_norm * 0.8
            vr = vr + dr * inv_d * pull + (-dc * inv_d) * swirl
            vc = vc + dc * inv_d * pull + (dr * inv_d) * swirl
            vr *= (0.88 - activity * 0.02)
            vc *= (0.88 - activity * 0.02)
            row += vr * 0.6
            col += vc * 0.6
            life -= (0.013 + (0.010 if activity < 0.25 else 0.0))
            if life > 0 and 0 <= row < rows and 0 <= col < cols:
                p[0], p[1], p[2], p[3], p[4] = row, col, vr, vc, life
                if write_idx != read_idx:
                    pool[write_idx], pool[read_idx] = pool[read_idx], pool[write_idx]
                write_idx += 1
                idx = idx_map[int(row) * cols + int(col)]
                if 0 <= idx < n_leds:
                    center_boost = min(1.0, inv_d / 3.2)

                    if pal_len > 0 and palette:
                        pidx = (color_pick % pal_len) * 3
                        color = (palette[pidx], palette[pidx + 1], palette[pidx + 2])
                    else:
                        color = spectrum_palette[color_pick % 12]

                    bright = min(1.0, life * (0.45 + pulse * 0.45) + center_boost * 0.45)
                    self._set_led(idx, color, int(bright * 255))

                    # Add a subtle tail to make orbital motion more visible.
                    back_row = int(row - vr * 1.2)
                    back_col = int(col - vc * 1.2)
                    if 0 <= back_row < rows and 0 <= back_col < cols:
                        idx_tail = idx_map[back_row * cols + back_col]
                        if 0 <= idx_tail < n_leds:
                            self._set_led(idx_tail, color, int((bright * 0.35) * 255))

        self._grav_count = write_idx

        # Core flash on strong bass to make the effect less "flat".
        if bass_norm > 0.72:
            c_row_i = int(c_row)
            c_col_i = int(c_col)
            for rr in range(c_row_i - 1, c_row_i + 2):
                for cc in range(c_col_i - 1, c_col_i + 2):
                    if 0 <= rr < self.rows and 0 <= cc < self.cols:
                        idx = self._idx_map[rr * self.cols + cc]
                        if 0 <= idx < self.n_leds:
                            self._set_led(idx, self._pal_color(self.pal_len // 6), 178)
    def render_pendulum_audio(self):
        """Audio-driven pendulum with decaying trail."""
        if not self._check_active(clear=True):
            return
        if not hasattr(self, '_pendulum_state'):
            self._pendulum_state = [0.0, 0.0]  # angle, angular velocity

        mv = self.c.mv_feat
        bass = float(mv[48])
        treble = float(mv[50])
        bass_n = bass / 255.0
        treble_n = treble / 255.0
        active = (bass > self.noise_threshold) or (treble > self.noise_threshold)

        angle, omega = self._pendulum_state
        if active:
            drive = (bass_n - 0.35) * 0.11
            omega += -0.03 * sin(angle) + drive
            omega *= 0.982 - treble_n * 0.03
            angle += omega
        else:
            # Fast settle to center when silence (no autonomous movement).
            omega *= 0.70
            angle *= 0.90
            # Also clear trail faster in silence so it doesn't look like sparkles.
            self._trail_count = 0

        self._pendulum_state[0], self._pendulum_state[1] = angle, omega

        rows = self.rows
        cols = self.cols
        idx_map = self._idx_map
        n_leds = self.n_leds

        pivot_row = 2
        pivot_col = (cols - 1) * 0.5
        length = (rows * 0.35) + bass_n * (rows * 0.35)
        bob_col = int(round(pivot_col + sin(angle) * ((cols - 1) * 0.95)))
        bob_row = int(pivot_row + abs(cos(angle)) * length)

        if bob_col < 0:
            bob_col = 0
        elif bob_col >= cols:
            bob_col = cols - 1
        if bob_row < 0:
            bob_row = 0
        elif bob_row >= rows:
            bob_row = rows - 1

        pool = self._ensure_trail_pool()
        if active:
            if self._trail_count < len(pool):
                slot = pool[self._trail_count]
                slot[0] = bob_row
                slot[1] = bob_col
                slot[2] = 1.0
                self._trail_count += 1

        write_idx = 0
        count = self._trail_count
        for i in range(count):
            tr = pool[i]
            row, col, life = tr
            life -= 0.08
            if life > 0:
                tr[2] = life
                if write_idx != i:
                    pool[write_idx], pool[i] = pool[i], pool[write_idx]
                write_idx += 1
                idx = idx_map[row * cols + col]
                if 0 <= idx < n_leds:
                    self._set_led(idx, self._pal_color(self.pal_len // 4), int((life * 0.45) * 255))
        self._trail_count = write_idx

        # Draw pendulum rod (visual distinction from sparkles).
        steps = bob_row - pivot_row
        if steps < 1:
            steps = 1
        for i in range(steps + 1):
            t_line = i / float(steps)
            rr = int(pivot_row + (bob_row - pivot_row) * t_line)
            cc = int(round(pivot_col + (bob_col - pivot_col) * t_line))
            if 0 <= rr < rows and 0 <= cc < cols:
                idxr = idx_map[rr * cols + cc]
                if 0 <= idxr < n_leds:
                    self._set_led(idxr, self._pal_color(self.pal_len // 3), int((0.08 + (0.10 if active else 0.03)) * 255))

        bob_color = self._warm_color(0.9) if active else self._pal_color(self.pal_len // 3)
        idx = idx_map[bob_row * cols + bob_col]
        if 0 <= idx < n_leds:
            self._set_led(idx, bob_color, int(((0.35 + bass_n * 0.55) if active else 0.12) * 255))


    def render_plasma_audio(self, speed=3.0, intensity=1.5):
        """Hybrid plasma-style renderer driven by audio_features components."""
        if not self._check_active(clear=False):
            return

        mv = self.c.mv_feat
        bass, mid, high = float(mv[48]), float(mv[49]), float(mv[50])
        bass_n = self._norm(bass)
        mid_n = self._norm(mid)
        high_n = self._norm(high)
        if high_n > 0.72 and mid_n > 0.50:
            self.render_quantum_rift()
            return
        if bass_n > 0.68 and intensity > 1.05:
            self.render_tunnel()
            return

        wave_h = int(14 + speed * 4 + intensity * 3 + bass_n * 24 + mid_n * 12)
        half = self.rows // 2
        if wave_h < 10:
            wave_h = 10
        elif wave_h > half:
            wave_h = half
        self.render_wave_audio(wave_height=wave_h)


    def render_presence_bloom(self):
        """Presence band (2–6 kHz) blooms outward from center; flux brightens onsets."""
        if not self._check_active(clear=False): return
        self.aled.apply_brightness_to_buffer(int(0.72 * 255))

        gb = self.brightness
        mv = self.c.mv_feat
        pal = self.c.palette
        pal_len = self.c.pal_length
        buf = self.buffer
        o0 = self.order0; o1 = self.order1; o2 = self.order2
        rows = self.rows; cols = self.cols
        energy = mv[51]; presence = mv[52]; flux = mv[54]
        beat = mv[44]; beat_str = mv[45]
        hue_base = mv[53] * 240 // 255
        hue_off = (time.ticks_ms() // 20) % 360

        # Calculate max radius based on columns/rows
        max_radius = max(rows, cols) * 0.7
        if max_radius < 1.0: max_radius = 1.0

        # Target radius based on presence energy
        target_radius = (presence * max_radius) / 255.0

        # Temporal smoothing for breathing effect
        if not hasattr(self, '_pb_smooth_radius'):
            self._pb_smooth_radius = 1.0
        self._pb_smooth_radius += (target_radius - self._pb_smooth_radius) * 0.25
        radius = self._pb_smooth_radius
        if radius < 0.5: radius = 0.5

        # Bloom from center outwards using pre-calculated distance map
        for idx in range(self.n_leds):
            dist = self._dist_map[idx]
            if dist > radius:
                continue

            # Falloff brightness from center to outer edge of the bloom
            t256 = int((radius - dist) * 256 / radius)
            if t256 < 0: t256 = 0

            # Outer ring boost on transients (flux)
            outer_boost = int(256 + ((flux * 205) >> 8)) if dist * 10.0 > radius * 7.0 else 256
            v = ((energy * t256) >> 8) * outer_boost >> 8
            
            # Add a baseline glow and boost via flux
            v = int(v * (1.0 + (flux / 50.0)))
            if v > 255: v = 255
            elif v < 30: v = 30 # minimum visible glow to prevent dark spots

            # Color mapping with shifting hue gradient
            hue_int = int(hue_base + hue_off + dist * 15) % 360
            pi = ((hue_int * pal_len) // 360) % pal_len * 3

            rr, gg, bb = self._pal_rgb(pi, v, gb)

            pos = idx * 3
            # Blend with existing buffer colors (maximum blending)
            buf[pos+o0] = max(buf[pos+o0], rr)
            buf[pos+o1] = max(buf[pos+o1], gg)
            buf[pos+o2] = max(buf[pos+o2], bb)

        # Draw onset beat flash
        if beat and beat_str > 76:
            flash_hue = (hue_base + hue_off + 180) % 360
            pi = ((flash_hue * pal_len) // 360) % pal_len * 3
            fr = (pal[pi] + 255) >> 1; fg = (pal[pi+1] + 255) >> 1; fb = (pal[pi+2] + 255) >> 1
            fv = beat_str * 50 >> 8
            rr = (fr * fv) >> 8; rr = (rr * gb) >> 8
            gg = (fg * fv) >> 8; gg = (gg * gb) >> 8
            bb = (fb * fv) >> 8; bb = (bb * gb) >> 8
            self.aled.aled_fill((rr, gg, bb))


    @micropython.native
    def render_quantum_rift(self):
        """WOW effect: fast spiral rift with full spectrum colors and punchy motion."""
        if not self._check_active():
            return
        mv = self.c.mv_feat
        bass = float(mv[48])
        mid = float(mv[49])
        high = float(mv[50])
        bass_n = self._norm(bass)
        mid_n = self._norm(mid)
        high_n = self._norm(high)
        active = (bass > self.noise_threshold) or (mid > self.noise_threshold) or (high > self.noise_threshold)
        if not active:
            return

        t = time.ticks_ms() / 1000.0
        speed = 1.6 + bass_n * 3.2 + high_n * 2.2
        core = 0.12 + bass_n * 0.48
        twist = 1.5 + high_n * 3.2
        beat_flash = 1.0 + bass_n * 0.6
        palette = self.spectrum_palette
        n_leds = self.n_leds
        rift_r = self._rift_r
        rift_a = self._rift_a
        idx_map = self._idx_map
        cols = self.cols

        for row in range(self.rows):
            row_off = row * cols
            for col in range(cols):
                idx = idx_map[row_off + col]
                if idx < 0 or idx >= n_leds:
                    continue
                r = rift_r[idx]
                if r < 0.0005:
                    r = 0.0005
                a = rift_a[idx]
                # Double the spin speed
                wave = abs(sin((r * 34.0 - t * speed * 8.0) + a * twist))
                core_glow = max(0.0, 1.0 - (r / core))
                val = max(core_glow, wave * (0.15 + high_n * 0.75))
                if val < 0.08:
                    continue
                # Double the color cycling speed
                color_idx = int((r * 40.0) + t * speed * 12.0 + a * 1.3) % 12
                color = palette[color_idx]
                bright = min(1.0, val * (0.35 + bass_n * 0.9 + mid_n * 0.5) * beat_flash)
                b = int(bright * 255)
                if b > 0:
                    self._set_led(idx, color, b)


    def render_radial_audio(self, start_row=0):
        """EXPLOSIVE Audio Burst - Particles shoot out from center!"""
        features = self._check_active(clear=False)
        if features is None:
            return
        if not hasattr(self, '_radial_capacity'):
            # Fixed particle pool to avoid runtime list growth (prevents MemoryError spikes).
            cap = self.n_leds // 5
            if cap < 24:
                cap = 24
            elif cap > 96:
                cap = 96
            self._radial_capacity = cap
            self._radial_count = 0
            self._radial_rows = array.array('f', [0.0] * cap)
            self._radial_cols = array.array('f', [0.0] * cap)
            self._radial_angles = array.array('f', [0.0] * cap)
            self._radial_vel = array.array('f', [0.0] * cap)
            self._radial_life = array.array('f', [0.0] * cap)
            self._radial_color_idx = bytearray(cap)

        self.aled.clear()

        center_row = self.rows / 2.0
        center_col = self.cols / 2.0

        rows = self._radial_rows
        cols = self._radial_cols
        angles = self._radial_angles
        vel = self._radial_vel
        life = self._radial_life
        color_idx = self._radial_color_idx
        capacity = self._radial_capacity
        count = self._radial_count

        bass = float(self.c.mv_feat[48])
        if bass > self.noise_threshold:
            bass_amp = bass / 255.0
            if bass_amp < 0.0:
                bass_amp = 0.0
            elif bass_amp > 1.5:
                bass_amp = 1.5

            # Spawn multiple particles when loud, but never exceed pool capacity.
            num_particles = int(bass_amp * 8)
            free_slots = capacity - count
            if num_particles > free_slots:
                num_particles = free_slots
            for _ in range(num_particles):
                rows[count] = center_row
                cols[count] = center_col
                angles[count] = random.random() * 6.283185307179586
                vel[count] = 0.5 + bass_amp * 2.0
                color_idx[count] = int(random.random() * 12)
                life[count] = 1.0
                count += 1

        # Update and render particles (in-place compaction, no temporary list allocations).
        write_idx = 0
        for i in range(count):
            row = rows[i] + sin(angles[i]) * vel[i]
            col = cols[i] + cos(angles[i]) * vel[i]
            lf = life[i] - 0.018

            if lf > 0.0 and 0 <= row < self.rows and 0 <= col < self.cols:
                rows[write_idx] = row
                cols[write_idx] = col
                angles[write_idx] = angles[i]
                vel[write_idx] = vel[i]
                life[write_idx] = lf
                color_idx[write_idx] = color_idx[i]
                write_idx += 1

                if row >= start_row:
                    idx = self._physical_index(int(col), int(row))
                    if 0 <= idx < self.n_leds:
                        self._set_led(idx, self.spectrum_palette[color_idx[write_idx - 1]], int(lf * 255))

        self._radial_count = write_idx


    def render_rain(self, start_row=0, fall_speed=1.0):
        """Rain drops falling - SMOOTH & SUB-PIXEL RENDERING"""
        if not self._check_active():
            return

        pool = self._ensure_rain_pool()
        bands = self.c.mv_bands

        # HUMIDITY affects drop frequency
        drop_chance = 0.15
        ctrl = self.c
        if ctrl:
            try:
                humidity = ctrl.humidity
                # High humidity = more rain (20-80% → 0.05-0.25)
                drop_chance = 0.05 + (humidity / 100.0) * 0.2
            except:
                pass

        rows = self.rows
        cols = self.cols
        idx_map = self._idx_map
        n_leds = self.n_leds
        spectrum_palette = self.spectrum_palette

        # Spawn new drops on audio beats
        for band_idx in range(12):
            raw_amp = bands[band_idx]
            if raw_amp > self.noise_threshold:
                amp = raw_amp / 255.0

                # Spawn drop with probability based on amplitude + humidity
                if random.random() < amp * drop_chance:
                    col = random.randint(0, cols - 1)
                    # SLOWER SPEED for smoothness (was 2.0 + amp*3.0)
                    speed = (0.5 + amp * 1.5) * fall_speed 
                    color = spectrum_palette[band_idx]
                    if self._rain_count < len(pool):
                        slot = pool[self._rain_count]
                        slot[0] = col
                        slot[1] = float(rows - 1)
                        slot[2] = speed
                        slot[3] = amp
                        slot[4] = color
                        self._rain_count += 1

        # Update drops (fall down) - in-place filter with reference swapping
        write_idx = 0
        count = self._rain_count
        for i in range(count):
            drop = pool[i]
            col, row, speed, brightness, color = drop
            row -= speed  # Fall
            
            if row > -2.0: # Keep until fully off screen
                drop[1] = row
                if write_idx != i:
                    pool[write_idx], pool[i] = pool[i], pool[write_idx]
                write_idx += 1

                # Render drop with SUB-PIXEL SMOOTHNESS
                # Integer part and fractional part
                i_row = int(row)
                frac = row - i_row
                
                # Draw head (interpolated)
                if row >= start_row:
                    # Current pixel gets (1-frac) brightness
                    if 0 <= i_row < rows:
                        idx = idx_map[i_row * cols + int(col)]
                        if 0 <= idx < n_leds:
                            self._set_led(idx, color, int((brightness * (1.0 - frac * 0.5)) * 255))

                    # Next pixel gets frac brightness (smooth movement)
                    if 0 <= i_row + 1 < rows:
                        idx = idx_map[(i_row + 1) * cols + int(col)]
                        if 0 <= idx < n_leds:
                            self._set_led(idx, color, int((brightness * frac * 0.5) * 255))

                    # Draw Trail (solid lines to prevent gaps)
                    trail_len = 3
                    for t in range(1, trail_len + 1):
                        t_row = i_row + t
                        if start_row <= t_row < rows:
                            # Fade out trail
                            t_bright = brightness * (1.0 - t / (trail_len + 1))
                            idx = idx_map[t_row * cols + int(col)]
                            if 0 <= idx < n_leds:
                                self._set_led(idx, color, int(t_bright * 255))

        self._rain_count = write_idx


    def render_spring_balls(self):
        """LASER COMET - Vertical bouncing comets with long gradient trails."""
        features = self._check_active(clear=False)
        if features is None:
            return
        comets = self._ensure_comets_pool()

        self.aled.clear()

        mv = self.c.mv_feat
        low, mid, high = float(mv[48]), float(mv[49]), float(mv[50])
        low_n = self._norm(low)
        mid_n = self._norm(mid)
        high_n = self._norm(high)
        active = (low > self.noise_threshold) or (mid > self.noise_threshold) or (high > self.noise_threshold)
        col_raw = [low_n, mid_n, high_n]
        max_raw = max(col_raw[0], col_raw[1], col_raw[2], 0.01)
        col_band = [0.18 + (v / max_raw) * 0.82 for v in col_raw]
        k = 0.04 + low_n * 0.12
        damping = 0.88 + (0.08 * (1.0 - high_n))
        base_center = self.rows * 0.5
        palette = self.spectrum_palette
        n_leds = self.n_leds
        idx_map = self._idx_map
        cols = self.cols
        rows = self.rows

        for col in range(cols):
            state = comets[col]
            pos, vel, target, color_idx = state
            amp = col_band[col if col < 3 else 2]
            # On beats, target jumps wildly; otherwise calmer
            base = base_center - amp * (rows * 0.35)
            if active:
                target = base
            else:
                target = base_center
            vel += (target - pos) * k
            vel *= damping
            pos += vel
            if pos < 0:
                pos = 0
                vel = -vel * 0.55
            elif pos > rows - 1:
                pos = rows - 1
                vel = -vel * 0.55
            state[0], state[1], state[2] = pos, vel, target

            # Color cycles on mid hits
            if mid_n > 0.5:
                state[3] = (state[3] + 1) % 12
            color = palette[state[3]]
            head_bright = 0.25 + amp * 0.75

            # Store head in trail buffer
            trail_buf = self._comet_trails[col]
            tlen = self._comet_trail_len[col]
            if tlen < len(trail_buf):
                trail_buf[tlen][0] = int(pos)
                trail_buf[tlen][1] = head_bright
                self._comet_trail_len[col] = tlen + 1
            else:
                # Shift trail down
                for i in range(len(trail_buf) - 1):
                    trail_buf[i][0] = trail_buf[i + 1][0]
                    trail_buf[i][1] = trail_buf[i + 1][1]
                trail_buf[-1][0] = int(pos)
                trail_buf[-1][1] = head_bright

            # Render trail (oldest = dimmest)
            tlen = self._comet_trail_len[col]
            for ti in range(tlen):
                tr = trail_buf[ti]
                trow = tr[0]
                tb = tr[1] * (0.15 + 0.85 * (ti / max(1, tlen - 1)))
                if tb > 0.05 and 0 <= trow < rows:
                    idx = idx_map[trow * cols + col]
                    if 0 <= idx < n_leds:
                        self._set_led(idx, color, int(tb * 255))

            # Render bright head + 1 pixel glow
            i_row = int(pos)
            if 0 <= i_row < rows:
                idx = idx_map[i_row * cols + col]
                if 0 <= idx < n_leds:
                    self._set_led(idx, color, int(head_bright * 255))
            glow_row = i_row - 1 if vel > 0 else i_row + 1
            if 0 <= glow_row < rows:
                idx = idx_map[glow_row * cols + col]
                if 0 <= idx < n_leds:
                    self._set_led(idx, color, int(head_bright * 0.4 * 255))

    def render_gravity_orbiters(self, gravity=1.5, friction=0.99, n_orbiters=2):
        """Gravity Orbiters: Particles orbit audio-reactive gravity centers."""
        if not self._check_active():
            return

        mv = self.c.mv_feat
        bass_n = self._norm(mv[48])
        mid_n = self._norm(mv[49])
        high_n = self._norm(mv[50])
        active = mv[51] > self.noise_threshold

        pool = self._ensure_orbit_pool()
        max_particles = len(pool)
        rows = self.rows
        cols = self.cols
        idx_map = self._idx_map
        n_leds = self.n_leds
        palette = self.spectrum_palette

        # Calculate orbiter positions
        t = time.ticks_ms() / 1000.0
        orbiters = []
        # Orbiter 1 (reacts to bass/mid)
        x1 = (cols * 0.5) + sin(t * 1.5) * (cols * 0.4)
        y1 = (rows * 0.5) + cos(t * 1.2) * (rows * 0.3)
        orbiters.append((x1, y1))
        
        if n_orbiters > 1:
            # Orbiter 2 (reacts to high/mid)
            x2 = (cols * 0.5) + cos(t * 2.0) * (cols * 0.3)
            y2 = (rows * 0.5) + sin(t * 1.8) * (rows * 0.25)
            orbiters.append((x2, y2))

        # Spawn particles
        if active and self._orbit_count < max_particles:
            spawn_prob = 0.1 + bass_n * 0.3
            if random.random() < spawn_prob:
                slot = pool[self._orbit_count]
                slot[0] = random.uniform(0, cols - 1)  # x
                slot[1] = random.uniform(0, rows - 1)  # y
                slot[2] = random.uniform(-1.0, 1.0)    # vx
                slot[3] = random.uniform(-1.0, 1.0)    # vy
                slot[4] = 1.0                          # life
                slot[5] = random.randint(0, 11)        # color_pick
                self._orbit_count += 1

        # Update and render particles
        write_idx = 0
        count = self._orbit_count
        for read_idx in range(count):
            p = pool[read_idx]
            px, py, pvx, pvy, life, color_pick = p

            # Apply gravity from all orbiters
            for ox, oy in orbiters:
                dx = ox - px
                dy = oy - py
                d2 = dx * dx + dy * dy
                if d2 < 0.1:
                    d2 = 0.1
                dist = sqrt(d2)
                # Gravity pull
                force = (gravity * 0.2) / dist
                pvx += force * (dx / dist)
                pvy += force * (dy / dist)

            pvx *= friction
            pvy *= friction
            px += pvx
            py += pvy
            life -= 0.008

            if life > 0:
                p[0], p[1], p[2], p[3], p[4] = px, py, pvx, pvy, life
                if write_idx != read_idx:
                    pool[write_idx], pool[read_idx] = pool[read_idx], pool[write_idx]
                write_idx += 1

                # Render
                ix = int(px)
                iy = int(py)
                if 0 <= ix < cols and 0 <= iy < rows:
                    idx = idx_map[iy * cols + ix]
                    if 0 <= idx < n_leds:
                        color = palette[color_pick]
                        self._set_led(idx, color, int(life * 255))
        self._orbit_count = write_idx

        # Render orbiters as bright indicators
        for ox, oy in orbiters:
            ix, iy = int(ox), int(oy)
            if 0 <= ix < cols and 0 <= iy < rows:
                idx = idx_map[iy * cols + ix]
                if 0 <= idx < n_leds:
                    self._set_led(idx, (255, 255, 255), 255)

    def render_gravity_cascade(self, gravity=0.15, wind=0.0, bounce=0.6):
        """Gravity Cascade: Particles fall from top and bounce off the bottom with wind."""
        if not self._check_active():
            return

        mv = self.c.mv_feat
        bass_n = self._norm(mv[48])
        active = mv[51] > self.noise_threshold

        pool = self._ensure_cascade_pool()
        max_particles = len(pool)
        rows = self.rows
        cols = self.cols
        idx_map = self._idx_map
        n_leds = self.n_leds
        palette = self.spectrum_palette

        # Spawn new particles at top on bass hits
        if active and self._cascade_count < max_particles:
            spawn_prob = 0.15 + bass_n * 0.45
            spawn_attempts = 1 + int(bass_n * 3.0)
            for _ in range(spawn_attempts):
                if self._cascade_count >= max_particles:
                    break
                if random.random() < spawn_prob:
                    slot = pool[self._cascade_count]
                    slot[0] = random.uniform(0, float(cols - 1) * 0.7) if cols > 1 else 0.0  # x
                    slot[1] = float(rows - 1)              # y (top)
                    slot[2] = random.uniform(0.08, 0.22) if cols > 1 else 0.0    # vx
                    slot[3] = 0.0                          # vy
                    slot[4] = 1.0                          # life
                    slot[5] = random.randint(0, 11)        # color
                    self._cascade_count += 1

        # Update and render cascade particles
        write_idx = 0
        count = self._cascade_count
        for read_idx in range(count):
            p = pool[read_idx]
            px, py, pvx, pvy, life, color_pick = p

            # Physics: gravity falls down (decreasing y)
            pvy -= gravity
            pvx += wind
            px += pvx
            py += pvy

            # Bounces off sides
            if px < 0:
                px = 0
                pvx = -pvx * bounce
            elif px > cols - 1:
                px = cols - 1
                pvx = -pvx * bounce

            # Bounces off bottom
            if py < 0:
                py = 0
                pvy = abs(pvy) * bounce
                # If too slow, slide/stop
                if pvy < 0.1:
                    pvy = 0.0
                    life -= 0.05  # decay faster on bottom

            life -= 0.01

            if life > 0:
                p[0], p[1], p[2], p[3], p[4] = px, py, pvx, pvy, life
                if write_idx != read_idx:
                    pool[write_idx], pool[read_idx] = pool[read_idx], pool[write_idx]
                write_idx += 1

                # Render
                ix = int(px)
                iy = int(py)
                if 0 <= ix < cols and 0 <= iy < rows:
                    idx = idx_map[iy * cols + ix]
                    if 0 <= idx < n_leds:
                        color = palette[color_pick]
                        self._set_led(idx, color, int(life * 255))
        self._cascade_count = write_idx

    def render_planet_orbit(self, gravity=2.0, speed=1.0, planet_count=3):
        """Planet Orbit: Elliptical orbits of planets around an audio-reactive sun."""
        if not self._check_active():
            return

        mv = self.c.mv_feat
        bass_n = self._norm(mv[48])
        mid_n = self._norm(mv[49])
        high_n = self._norm(mv[50])

        rows = self.rows
        cols = self.cols
        idx_map = self._idx_map
        n_leds = self.n_leds
        palette = self.spectrum_palette

        # Sun center
        cx = cols * 0.5
        cy = rows * 0.5

        # Draw sun (reactive size/brightness)
        sun_radius = 1 + int(bass_n * 3.0)
        sun_brightness = 150 + int(bass_n * 105)
        for dy in range(-sun_radius, sun_radius + 1):
            for dx in range(-sun_radius, sun_radius + 1):
                if dx*dx + dy*dy <= sun_radius*sun_radius:
                    ix = int(cx + dx)
                    iy = int(cy + dy)
                    if 0 <= ix < cols and 0 <= iy < rows:
                        idx = idx_map[iy * cols + ix]
                        if 0 <= idx < n_leds:
                            self._set_led(idx, (255, 120 + int(mid_n * 135), 0), sun_brightness)

        # Draw orbiting planets
        t = time.ticks_ms() / 1000.0
        for i in range(planet_count):
            # Orbit size depends on index and gravity
            rx = (i + 1) * (cols / (planet_count + 1.5)) * (1.0 + gravity * 0.05)
            ry = (i + 1) * (rows / (planet_count + 1.5)) * (1.0 + gravity * 0.05)
            
            # Orbit angle
            angle = t * speed * (1.5 / (i + 1))
            
            px = cx + sin(angle) * rx
            py = cy + cos(angle) * ry

            # Draw planet
            ix = int(px)
            iy = int(py)
            color = palette[(i * 4) % 12]
            
            if 0 <= ix < cols and 0 <= iy < rows:
                idx = idx_map[iy * cols + ix]
                if 0 <= idx < n_leds:
                    self._set_led(idx, color, 255)
                    
            # Tiny moons / particles around planet on high frequency hits
            if high_n > 0.4:
                ma = angle * 3.0
                mx = px + sin(ma) * 1.2
                my = py + cos(ma) * 1.2
                mix = int(mx)
                miy = int(my)
                if 0 <= mix < cols and 0 <= miy < rows:
                    m_idx = idx_map[miy * cols + mix]
                    if 0 <= m_idx < n_leds:
                        self._set_led(m_idx, (255, 255, 255), 180)

    def render_black_hole(self, gravity=2.5, swallow_radius=2.0, particle_count=80):
        """Black Hole: Outer boundary particles pulled and swallowed at center."""
        if not self._check_active():
            return

        mv = self.c.mv_feat
        bass_n = self._norm(mv[48])
        mid_n = self._norm(mv[49])
        active = mv[51] > self.noise_threshold

        pool = self._ensure_blackhole_pool()
        max_particles = min(particle_count, len(pool))
        rows = self.rows
        cols = self.cols
        idx_map = self._idx_map
        n_leds = self.n_leds
        palette = self.spectrum_palette

        cx = cols * 0.5
        cy = rows * 0.5

        # Initialize particles if count is low
        if self._blackhole_count < max_particles:
            for _ in range(max_particles - self._blackhole_count):
                slot = pool[self._blackhole_count]
                # Spawn at edges
                edge = random.randint(0, 3)
                if edge == 0:
                    slot[0], slot[1] = 0.0, random.uniform(0, rows - 1)
                elif edge == 1:
                    slot[0], slot[1] = float(cols - 1), random.uniform(0, rows - 1)
                elif edge == 2:
                    slot[0], slot[1] = random.uniform(0, cols - 1), 0.0
                else:
                    slot[0], slot[1] = random.uniform(0, cols - 1), float(rows - 1)
                
                slot[2] = 0.0                     # vx
                slot[3] = 0.0                     # vy
                slot[4] = 0.5 + random.random()   # life
                slot[5] = random.randint(0, 11)   # color
                self._blackhole_count += 1

        # Swallow center flash tracker
        flash_intensity = int(bass_n * 150)

        # Update and render black hole particles
        for i in range(self._blackhole_count):
            p = pool[i]
            px, py, pvx, pvy, life, color_pick = p

            dx = cx - px
            dy = cy - py
            d2 = dx * dx + dy * dy
            if d2 < 0.1:
                d2 = 0.1
            dist = sqrt(d2)

            if dist < swallow_radius:
                # Swallow and respawn at edge
                edge = random.randint(0, 3)
                if edge == 0:
                    px, py = 0.0, random.uniform(0, rows - 1)
                elif edge == 1:
                    px, py = float(cols - 1), random.uniform(0, rows - 1)
                elif edge == 2:
                    px, py = random.uniform(0, cols - 1), 0.0
                else:
                    px, py = random.uniform(0, cols - 1), float(rows - 1)
                pvx = 0.0
                pvy = 0.0
                life = 0.5 + random.random()
            else:
                # Pull towards center
                pull = (gravity * 0.1 * (1.0 + bass_n * 0.5)) / dist
                pvx += pull * (dx / dist)
                pvy += pull * (dy / dist)
                
                # Apply friction/drag to prevent slingshots
                pvx *= 0.94
                pvy *= 0.94
                
                px += pvx
                py += pvy

            p[0], p[1], p[2], p[3], p[4] = px, py, pvx, pvy, life

            # Render
            ix = int(px)
            iy = int(py)
            if 0 <= ix < cols and 0 <= iy < rows:
                idx = idx_map[iy * cols + ix]
                if 0 <= idx < n_leds:
                    color = palette[color_pick]
                    self._set_led(idx, color, int(life * 255))

        # Render the black hole center (a sucking void / reactive white/blue spot)
        ix = int(cx)
        iy = int(cy)
        if 0 <= ix < cols and 0 <= iy < rows:
            idx = idx_map[iy * cols + ix]
            if 0 <= idx < n_leds:
                self._set_led(idx, (flash_intensity, flash_intensity, 255), 255)

    def render_tunnel(self):
        """TUNNEL - Audio-reactive tunnel effect."""
        features = self._check_active()
        if features is None:
            return

        t = time.ticks_ms() / 1000.0
        mv = self.c.mv_feat
        bass_norm = self._norm(mv[48])
        mid_norm = self._norm(mv[49])

        fov = 1.0 + bass_norm * 3.0
        core_radius = 0.18 + bass_norm * 0.55
        spin = t * (1.0 + mid_norm * 3.0)
        palette = self.spectrum_palette
        n_leds = self.n_leds
        tunnel_dist = self._tunnel_dist
        idx_map = self._idx_map
        cols = self.cols

        for row in range(self.rows):
            row_off = row * cols
            for col in range(cols):
                idx = idx_map[row_off + col]
                if idx < 0 or idx >= n_leds:
                    continue
                dist = tunnel_dist[idx]
                if dist < core_radius:
                    core_b = int((0.4 + bass_norm * 0.6) * 255)
                    if core_b > 0:
                        self._set_led(idx, palette[int(bass_norm * 6) % 12], core_b)
                    continue
                z = fov / dist
                color_idx = int(z + spin) % 12
                brightness = (1.0 - dist * 0.15) * (0.5 + bass_norm * 0.5)
                if brightness > 0.05:
                    if int(z) % 8 == 0:
                        brightness = min(1.0, brightness * 1.8)
                    b = int(max(0.0, min(1.0, brightness)) * 255)
                    if b > 0:
                        self._set_led(idx, palette[color_idx], b)


    def render_vibrant_lights(self):
        """SPECTACULAR Vibrant Scanlines - Fast, colorful, audio-reactive"""

        features = self._check_active()
        if features is None:
            return

        t = time.ticks_ms() / 1000.0
        energy_level = float(self.c.mv_feat[51])
        energy_norm = self._norm(energy_level)
        active = energy_level > self.noise_threshold * 0.8
        if not active:
            return

        cols = self.cols
        n_leds = self.n_leds
        idx_map = self._idx_map
        rows = self.rows
        palette = self.spectrum_palette

        for i in range(5):
            speed = (0.10 + energy_norm * 2.4)
            pos_float = (t * (speed + i * 0.15) + sin(t * (0.5 + energy_norm * 2.0) + i)) % 1.0
            row = int(pos_float * rows)
            color = palette[(i * 2) % 12]
            width = int(1 + energy_norm * 5)

            for r_off in range(-width, width + 1):
                curr_row = row + r_off
                if 0 <= curr_row < rows:
                    dist = abs(r_off)
                    brightness = (1.0 - dist / (width + 1)) * (0.22 + energy_norm * 0.78)
                    row_off = curr_row * cols
                    for col in range(cols):
                        idx = idx_map[row_off + col]
                        if 0 <= idx < n_leds:
                            self._set_led(idx, color, int(brightness * 255))


    def render_wave_audio(self, wave_height=40, start_row=0):
        """FAST Interweaving Waves - 2 sin calls per pixel max."""

        features = self._check_active()
        if features is None:
            return
        bands = self.c.mv_bands

        t = time.ticks_ms() / 1000.0
        pi2 = 2.0 * pi
        rows = self.rows
        cols = self.cols
        n_leds = self.n_leds
        idx_map = self._idx_map
        palette = self.spectrum_palette
        half_rows = rows // 2
        norm_base = 255.0
        high_norm = self._norm(self.c.mv_feat[50])
        bright_color = self._pal_color(self.pal_len // 6) if self.pal_len > 0 else (255, 255, 255)

        # Parametrized column configuration for any display width
        col_cfg = []
        for c_idx in range(cols):
            # Distribute 12 bands across available columns
            b_start = (c_idx * 12) // cols
            b_end = ((c_idx + 1) * 12) // cols
            if b_end <= b_start: b_end = b_start + 1
            
            # Average the bands for this column
            band_sum = 0.0
            count = 0
            for b in range(b_start, min(b_end, 12)):
                band_sum += bands[b]
                count += 1
            avg_amp = band_sum / count if count > 0 else 0.0
            
            # Sensitivity varies by frequency (lower for bass, higher for treble)
            sens = 1.0 + (b_start / 12.0) * 0.5
            col_cfg.append((avg_amp, b_start, sens))

        for col in range(cols):
            raw_amp, base_color_idx, sensitivity = col_cfg[col]
            if raw_amp < self.noise_threshold:
                continue
            amp_norm = (raw_amp / norm_base) * sensitivity
            if amp_norm > 1.0:
                amp_norm = 1.0
            phase_shift = t * (2.2 + amp_norm * 6.2) + col * (0.35 + high_norm * 0.5)
            col_phase = phase_shift + col * 0.5

            for row in range(start_row, rows):
                y = row / rows
                wave_phase = pi2 * 1.5 * y + col_phase
                total_disp = int(sin(wave_phase) * wave_height * amp_norm +
                                 sin(wave_phase * 2.0 + pi * 0.5) * wave_height * 0.5 * amp_norm)
                wave_center = half_rows + total_disp
                dist = row - wave_center
                if dist < 0:
                    dist = -dist
                if dist < 14:
                    brightness = amp_norm * (1.0 - dist / 14.0)
                    if dist < 2.5 and amp_norm > 0.5:
                        brightness = 0.8 + high_norm * 0.4
                        if brightness > 1.0:
                            brightness = 1.0
                        color = bright_color
                    else:
                        color_idx = (base_color_idx + int((y * 4 + t * (0.3 + high_norm * 1.2))) % 5) % 12
                        color = palette[color_idx]
                    idx = idx_map[row * cols + col]
                    if 0 <= idx < n_leds:
                        self._set_led(idx, color, int(brightness * 255))

    def render_pulse(self, color=(0, 180, 255)):
        """Pulse effect. Circle/chords pulse on 19x19 matrix, full color pulse on others."""
        if not self._check_active(): return
        energy = self.c.mv_feat[51]
        gb = self.brightness
        if self.rows == 19 and self.cols == 19:
            pal = self.c.palette
            pal_len = self.pal_len
            buf = self.buffer
            o0, o1, o2 = self.order0, self.order1, self.order2
            hue_int = (time.ticks_ms() // 20) % 360
            pi = hue_int * pal_len // 360 * 3
            rr, gg, bb = self._pal_rgb(pi, energy, gb)
            for i in LED1_CIRCLE_CW:
                pos = i * 3
                buf[pos+o0] = rr; buf[pos+o1] = gg; buf[pos+o2] = bb
            dim_e = (energy * 77) >> 8
            dr, dg, db = self._pal_rgb(pi, dim_e, gb)
            for i in LED1_INNER_ARC_V + LED1_TREE_ALL_V:
                pos = i * 3
                buf[pos+o0] = dr; buf[pos+o1] = dg; buf[pos+o2] = db
        else:
            r, g, bv = color
            rr = (r * energy) >> 8; rr = (rr * gb) >> 8
            gg = (g * energy) >> 8; gg = (gg * gb) >> 8
            bb = (bv * energy) >> 8; bb = (bb * gb) >> 8
            self.aled.aled_fill((rr, gg, bb))

    def render_rotating(self, hue_offset=0.0):
        """Rotating Grid: Each column/row is a frequency band, rotation via column shift."""
        if not self._check_active(clear=True): return
        c = self.c
        mv_b = c.mv_bands
        pal = self.spectrum_palette
        
        if self.rows == 19 and self.cols == 19:
            t_shift = (time.ticks_ms() // 100) % 18
            for col in range(18):
                logical_col = (col + t_shift) % 18
                band_idx = (logical_col * 12) // 18
                val = mv_b[band_idx]
                if val < self.noise_threshold: continue
                color = pal[band_idx]
                for row in range(5):
                    idx = self._physical_index(col, row)
                    if idx >= 0: self._set_led(idx, color, val)
        else:
            cols = self.cols
            rows = self.rows
            t_shift = (time.ticks_ms() // 200) % cols
            for col in range(cols):
                logical_col = (col + t_shift) % cols
                band_idx = (logical_col * 12) // cols
                val = mv_b[band_idx]
                if val < self.noise_threshold: continue
                color = pal[band_idx]
                for row in range(rows):
                    idx = self._physical_index(col, row)
                    if idx >= 0: self._set_led(idx, color, val)

    def render_spectrum(self, hue_offset=0.0):
        """Circle EQ/Radial Spectrum: Fills radially from center row outward."""
        if not self._check_active(clear=True): return
        c = self.c
        mv_b = c.mv_bands
        pal = self.spectrum_palette
        
        if self.rows == 19 and self.cols == 19:
            for col in range(18):
                band_idx = (col * 12) // 18
                val = mv_b[band_idx]
                if val < self.noise_threshold: continue
                h = (val * 3) >> 8
                color = pal[band_idx]
                for r_off in range(h + 1):
                    for r in (2-r_off, 2+r_off):
                        if 0 <= r < 5:
                            idx = self._physical_index(col, r)
                            if idx >= 0: self._set_led(idx, color, val)
        else:
            cols = self.cols
            rows = self.rows
            center_row = rows // 2
            for col in range(cols):
                band_idx = (col * 12) // cols
                val = mv_b[band_idx]
                if val < self.noise_threshold: continue
                h = (val * (rows // 2)) >> 8
                color = pal[band_idx]
                for r_off in range(h + 1):
                    for r in (center_row - r_off, center_row + r_off):
                        if 0 <= r < rows:
                            idx = self._physical_index(col, r)
                            if idx >= 0: self._set_led(idx, color, val)

    def render_spectrum1(self):
        """Segmented spectrum: maps specific frequency bands to physical segments."""
        if not self._check_active():
            return
        gb = self.brightness
        mv_b = self.c.mv_bands
        mv = self.c.mv_feat
        pal = self.c.palette
        pal_len = self.pal_len
        buf = self.buffer
        o0, o1, o2 = self.order0, self.order1, self.order2
        
        if self.rows == 19 and self.cols == 19:
            n = len(LED1_CIRCLE_CW)
            lpp = max(1, n // 12)
            for band in range(12):
                val = mv_b[band]
                hue_int = (240 - band * 20) % 360
                pi = hue_int * pal_len // 360 * 3
                rr, gg, bb = self._pal_rgb(pi, val, gb)
                start = band * lpp; end = min(start + lpp, n)
                for j in range(start, end):
                    pos = LED1_CIRCLE_CW[j] * 3
                    buf[pos+o0] = rr; buf[pos+o1] = gg; buf[pos+o2] = bb
            pi = 220 * pal_len // 360 * 3
            val = mv[48]
            rr, gg, bb = self._pal_rgb(pi, val, gb)
            for i in LED1_INNER_ARC_V:
                pos = i * 3; buf[pos+o0] = rr; buf[pos+o1] = gg; buf[pos+o2] = bb
            pi = 120 * pal_len // 360 * 3
            val = mv[49]
            rr, gg, bb = self._pal_rgb(pi, val, gb)
            for i in LED1_TREE_ALL_V:
                pos = i * 3; buf[pos+o0] = rr; buf[pos+o1] = gg; buf[pos+o2] = bb
        else:
            n = self.n_leds
            seg1 = int(n * 0.5)
            seg2 = int(n * 0.75)
            lpp = max(1, seg1 // 12)
            for band in range(12):
                val = mv_b[band]
                hue_int = (240 - band * 20) % 360
                pi = hue_int * pal_len // 360 * 3
                rr, gg, bb = self._pal_rgb(pi, val, gb)
                start = band * lpp; end = min(start + lpp, seg1)
                for j in range(start, end):
                    pos = j * 3
                    buf[pos+o0] = rr; buf[pos+o1] = gg; buf[pos+o2] = bb
            pi = 220 * pal_len // 360 * 3
            val = mv[48]
            rr, gg, bb = self._pal_rgb(pi, val, gb)
            for j in range(seg1, seg2):
                pos = j * 3
                buf[pos+o0] = rr; buf[pos+o1] = gg; buf[pos+o2] = bb
            pi = 120 * pal_len // 360 * 3
            val = mv[49]
            rr, gg, bb = self._pal_rgb(pi, val, gb)
            for j in range(seg2, n):
                pos = j * 3
                buf[pos+o0] = rr; buf[pos+o1] = gg; buf[pos+o2] = bb

    def render_energy_bars(self):
        """3 columns: bass / mid / treble — fills from bottom (row 0). Direct buffer writes."""
        if not self._check_active(): return
        gb = self.brightness
        mv = self.c.mv_feat
        pal = self.c.palette
        pal_len = self.pal_len
        buf = self.buffer
        o0, o1, o2 = self.order0, self.order1, self.order2
        rows, cols = self.rows, self.cols
        idx_map = self._idx_map
        n_leds = self.n_leds
        hue_ints = (0, 120, 240)
        for col in range(min(cols, 3)):
            fill = (mv[48 + col] * rows) >> 8
            pi = hue_ints[col] * pal_len // 360 * 3
            pr, pg, pb = pal[pi], pal[pi+1], pal[pi+2]
            for row in range(rows):
                idx = idx_map[row * cols + col]
                if 0 <= idx < n_leds:
                    pos = idx * 3
                    if row < fill:
                        v_scale = 90 + (row * 165) // rows
                        rr, gg, bb = self._pal_rgb(pi, v_scale, gb)
                        buf[pos+o0] = rr; buf[pos+o1] = gg; buf[pos+o2] = bb
                    else:
                        buf[pos] = 0; buf[pos+1] = 0; buf[pos+2] = 0

    def render_gradient_energy(self):
        if not self._check_active(): return
        gb = self.brightness
        energy = self.c.mv_feat[51]
        pal = self.c.palette
        pal_len = self.pal_len
        buf = self.buffer
        o0, o1, o2 = self.order0, self.order1, self.order2
        rows, cols = self.rows, self.cols
        idx_map = self._idx_map
        n_leds = self.n_leds
        rows_m1 = max(1, rows - 1)
        for col in range(cols):
            for row in range(rows):
                t256 = row * 256 // rows_m1
                hue_int = (col * 60 + (t256 * 120) // 256) % 360
                pi = hue_int * pal_len // 360 * 3
                val = (energy * (77 + ((179 * t256) >> 8))) >> 8
                rr, gg, bb = self._pal_rgb(pi, val, gb)
                idx = idx_map[row * cols + col]
                if 0 <= idx < n_leds:
                    pos = idx * 3
                    buf[pos+o0] = rr; buf[pos+o1] = gg; buf[pos+o2] = bb

    def render_spectrum_matrix(self):
        if not self._check_active(): return
        gb = self.brightness
        mv_b = self.c.mv_bands
        pal = self.c.palette
        pal_len = self.pal_len
        buf = self.buffer
        o0, o1, o2 = self.order0, self.order1, self.order2
        rows, cols = self.rows, self.cols
        idx_map = self._idx_map
        n_leds = self.n_leds
        rows_m1 = max(1, rows - 1)
        bands_per_col = max(1, 12 // cols)
        for col in range(cols):
            b_start = col * bands_per_col
            b_end = min(b_start + bands_per_col, 12) - 1
            for row in range(rows):
                t256 = row * 256 // rows_m1
                b = b_start + t256 * (b_end - b_start + 1) // 256
                if b > b_end: b = b_end
                val = mv_b[b]
                hue_int = (col * 90 + (t256 * 30) // 256) % 360
                pi = hue_int * pal_len // 360 * 3
                rr, gg, bb = self._pal_rgb(pi, val, gb)
                idx = idx_map[row * cols + col]
                if 0 <= idx < n_leds:
                    pos = idx * 3
                    buf[pos+o0] = rr; buf[pos+o1] = gg; buf[pos+o2] = bb

    def render_waterfall(self):
        if not self._check_active(): return
        gb = self.brightness
        mv_b = self.c.mv_bands
        pal = self.c.palette
        pal_len = self.pal_len
        buf = self.buffer
        o0, o1, o2 = self.order0, self.order1, self.order2
        rows, cols = self.rows, self.cols
        idx_map = self._idx_map
        n_leds = self.n_leds
        row_bytes = cols * 3
        
        global _wfall2
        needed = rows * cols * 3
        if len(_wfall2) < needed:
            _wfall2 = bytearray(needed)
            
        for row in range(rows - 1):
            src = (row + 1) * row_bytes; dst = row * row_bytes
            _wfall2[dst:dst+row_bytes] = _wfall2[src:src+row_bytes]
        top = (rows - 1) * row_bytes
        for col in range(cols):
            b = (col * 12) // cols
            if b > 11: b = 11
            val = mv_b[b]
            hue_int = col * 100 % 360
            pi = hue_int * pal_len // 360 * 3
            off = top + col * 3
            _wfall2[off], _wfall2[off+1], _wfall2[off+2] = self._pal_rgb(pi, val, 255)
        for row in range(rows):
            for col in range(cols):
                off = row * row_bytes + col * 3
                idx = idx_map[row * cols + col]
                if 0 <= idx < n_leds:
                    pos = idx * 3
                    buf[pos+o0] = (_wfall2[off]   * gb) >> 8
                    buf[pos+o1] = (_wfall2[off+1] * gb) >> 8
                    buf[pos+o2] = (_wfall2[off+2] * gb) >> 8

    def render_sandclock(self, speed=1.0, color_p=(230, 160, 10), y_min=None, y_max=None, half=None, **kwargs):
        """Hourglass/Sandclock animation correlated with the current seconds (60s period).

        Parameters:
            speed   – falling grain speed multiplier (default 1.0)
            color_p – RGB tuple for the sand grain color (default warm amber)
            y_min   – start row of the active display range
            y_max   – end row of the active display range
            half    – 'upper' or 'lower' half configuration
        """
        rows = self.rows
        cols = self.cols
        idx_map = self._idx_map
        n_leds = self.n_leds

        # Use controller time (same source as analog_clock) — no audio gate
        sec = self.c.seconds

        # Calculate bounding rows
        ymin = 0 if y_min is None else y_min
        ymax = (rows - 1) if y_max is None else y_max
        if half == 'upper':
            ymin = rows // 2
        elif half == 'lower':
            ymax = rows // 2 - 1

        h_range = ymax - ymin + 1
        # Neck row: centre of the active range.
        neck = ymin + h_range // 2

        # Rebuild coordinate lists whenever dimensions change (or first call)
        if (not hasattr(self, "_sc_neck") or self._sc_neck != neck or
            getattr(self, "_sc_ymin", None) != ymin or getattr(self, "_sc_ymax", None) != ymax):
            self._sc_neck = neck
            self._sc_ymin = ymin
            self._sc_ymax = ymax

            centre = (cols - 1) / 2.0
            shelf_pixels = set()
            for x in range(cols):
                # Always add the neck row pixel for all columns to form the horizontal separator
                shelf_pixels.add((x, neck))

                dist = abs(x - centre)
                if cols > 2 and dist >= 1.0:
                    dy = int(dist)
                    for y_shelf in range(max(ymin, neck - dy), min(ymax + 1, neck + dy + 1)):
                        shelf_pixels.add((x, y_shelf))
            self._shelf_pixels = shelf_pixels

            top_coords = []
            for y in range(neck + 1, ymax + 1):
                for x in range(cols):
                    if (x, y) not in shelf_pixels:
                        top_coords.append((x, y))
            # Sort so grains at the top drain first (decreasing from top to neck/center)
            top_coords.sort(key=lambda c: (ymax - c[1]) * 10 + abs(c[0] - (cols - 1) / 2.0))
            self._top_coords = top_coords

            bottom_coords = []
            for y in range(ymin, neck):
                for x in range(cols):
                    if (x, y) not in shelf_pixels:
                        bottom_coords.append((x, y))
            # Sort so grains pile from the bottom up, centred
            bottom_coords.sort(key=lambda c: (c[1] - ymin) * 10 + abs(c[0] - (cols - 1) / 2.0))
            self._bottom_coords = bottom_coords

            self._sand_particles = []
            self._last_sec = sec

        # Calculate smooth progress from 0.0 to 1.0 over a 60-second period.
        # We synchronize ticks_ms with RTC seconds to get a monotonic and smooth float second.
        # We scale time so the sand finishes falling at 58.0 seconds, leaving 2 seconds of final state.
        now_ms = time.ticks_ms()
        if not hasattr(self, "_minute_start_ticks") or (sec == 0 and self._last_sec != 0):
            # If initializing, estimate start ticks based on current sec
            if not hasattr(self, "_minute_start_ticks"):
                self._minute_start_ticks = time.ticks_add(now_ms, -int(sec * 1000))
            else:
                self._minute_start_ticks = now_ms

        current_time = time.ticks_diff(now_ms, self._minute_start_ticks) / 1000.0
        current_time = max(0.0, min(60.0, current_time))
        
        if current_time >= 58.0:
            progress = 1.0
        else:
            progress = current_time / 58.0

        # Number of grains in top/bottom chambers
        N_top = len(self._top_coords)
        N_bottom = len(self._bottom_coords)

        # target_bottom goes from 0 to N_bottom
        target_bottom = int(progress * N_bottom)
        # target_top goes from N_top to 0
        target_top = N_top - int(progress * N_top)

        active_top    = self._top_coords[N_top - target_top:]
        active_bottom = self._bottom_coords[:target_bottom]

        # Reset particles on minute rollover
        if sec != self._last_sec:
            if sec == 0:
                self._sand_particles.clear()
            self._last_sec = sec

        # Find height of bottom pile per column (for landing detection)
        pile_heights = [ymin - 1] * cols
        for x, y in active_bottom:
            if y > pile_heights[x]:
                pile_heights[x] = y

        # Spawn a falling grain from the neck
        if target_top > 0 and random.random() < 0.4:
            centre = (cols - 1) / 2.0
            spawn_x = int(centre + random.choice([-0.5, 0.5])) if cols > 2 else 0
            spawn_x = max(0, min(cols - 1, spawn_x))
            grain_speed = (1.2 + random.random() * 0.4) * speed
            self._sand_particles.append([float(neck), spawn_x, grain_speed])

        # Update falling grains
        active_falling = []
        for p in self._sand_particles:
            py, px, gs = p
            py -= gs
            col_x = int(px)
            if py <= pile_heights[col_x] + 1:
                continue          # grain landed — skip it (already in active_bottom)
            p[0] = py
            active_falling.append(p)
        self._sand_particles = active_falling

        # Clear display
        self.aled.clear()

        # Draw neck boundary shelf (red funnel line)
        shelf_color = (180, 0, 0)
        for x, y in self._shelf_pixels:
            idx = idx_map[y * cols + x]
            if 0 <= idx < n_leds:
                self._set_led(idx, shelf_color, 255)

        # Draw static top and bottom sand
        cr, cg, cb = color_p[0], color_p[1], color_p[2]
        sand_color = (cr, cg, cb)
        for x, y in active_top:
            idx = idx_map[y * cols + x]
            if 0 <= idx < n_leds:
                self._set_led(idx, sand_color, 255)
        for x, y in active_bottom:
            idx = idx_map[y * cols + x]
            if 0 <= idx < n_leds:
                self._set_led(idx, sand_color, 255)

        # Draw falling grains (slightly brighter / yellower)
        falling_color = (min(255, cr + 25), min(255, cg + 50), min(255, cb + 40))
        for py, px, gs in self._sand_particles:
            iy, ix = int(py), int(px)
            if 0 <= ix < cols and ymin <= iy <= ymax:
                idx = idx_map[iy * cols + ix]
                if 0 <= idx < n_leds:
                    self._set_led(idx, falling_color, 255)

        self.update()

    def _get_fountain_palette(self, palette_id):
        # Dynamically sample start/end colors from the global c.palette
        pal_len = self.pal_len
        if pal_len <= 0 or not self.c.palette:
            # Fallback if palette is empty
            if palette_id == 0: return ((255, 0, 180), (0, 100, 255))
            if palette_id == 1: return ((255, 230, 0), (150, 0, 0))
            if palette_id == 2: return ((50, 255, 0), (180, 0, 255))
            if palette_id == 3: return ((0, 255, 200), (120, 0, 255))
            return ((255, 255, 255), (80, 80, 80))

        if palette_id == 0: # Cyberpunk (Pink -> Blue)
            return (self._pal_color(int(pal_len * 0.85)), self._pal_color(int(pal_len * 0.65)))
        elif palette_id == 1: # Fire (Yellow -> Red)
            return (self._pal_color(int(pal_len * 0.12)), self._pal_color(int(pal_len * 0.0)))
        elif palette_id == 2: # Toxic (Green -> Purple)
            return (self._pal_color(int(pal_len * 0.28)), self._pal_color(int(pal_len * 0.80)))
        elif palette_id == 3: # Aurora (Teal -> Violet)
            return (self._pal_color(int(pal_len * 0.50)), self._pal_color(int(pal_len * 0.72)))
        else: # Monochrome / Custom
            return ((255, 255, 255), (80, 80, 80))

    def _ensure_fountain_pool(self, max_particles=40):
        if not hasattr(self, '_fountain_particles') or self._fountain_particles is None:
            self._fountain_particles = array.array('f', [0.0] * (max_particles * 6))
            self._fountain_palettes = array.array('B', [0] * max_particles)
            self._fountain_max_p = max_particles
        elif self._fountain_max_p < max_particles:
            self._fountain_particles = array.array('f', [0.0] * (max_particles * 6))
            self._fountain_palettes = array.array('B', [0] * max_particles)
            self._fountain_max_p = max_particles
        return self._fountain_particles, self._fountain_palettes

    def spawn_fountain_particle(self, start_x, start_y, angle, speed, palette_id, max_particles):
        scale_x = sqrt(self.cols / 16.0)
        scale_y = sqrt(self.rows / 52.0)
        particles, palettes = self._ensure_fountain_pool(max_particles)
        for i in range(max_particles):
            idx = i * 6
            if particles[idx + 5] == 0.0:
                particles[idx] = float(start_x)
                particles[idx + 1] = float(start_y)
                particles[idx + 2] = float(speed * (_fast_cos(angle) / 127.0) * scale_x)
                particles[idx + 3] = float(speed * (_fast_sin(angle) / 127.0) * scale_y)
                particles[idx + 4] = 1.0
                particles[idx + 5] = 1.0
                palettes[i] = palette_id & 0xFF
                break

    @micropython.native
    def render_gravity_fountain(self, gravity=0.15, bounce=0.6, wind=0.01, color_mode=0, decay_rate=0.025, max_particles=40, enable_ghosting=False, ghosting_factor=0.7, audio_reactive=True):
        # Ensure pools
        particles, palettes = self._ensure_fountain_pool(max_particles)
        
        # Audio level: energy level normalized
        is_active = self.c.mv_feat[51] if (hasattr(self.c, 'mv_feat') and len(self.c.mv_feat) > 51) else False
        audio_level = self._norm(self.c.mv_feat[51]) if is_active else 0.0

        # Scale physics parameters to fit matrix size
        scale_x = sqrt(self.cols / 16.0)
        scale_y = sqrt(self.rows / 52.0)
        scaled_wind = wind * scale_x

        # Apply ghosting trail or clear buffer
        self._ghosting_or_clear(enable_ghosting, ghosting_factor)

        # Count active particles
        active_count = 0
        for i in range(max_particles):
            if particles[i * 6 + 5] == 1.0:
                active_count += 1

        # Determine how many particles to spawn
        num_to_spawn = 0
        
        # Audio triggering
        if audio_reactive and audio_level > 0.15:
            # Spawn based on audio level
            num_to_spawn = int(audio_level * 5)
        
        # Auto-spawning fallback (if not audio reactive, or if audio is silent and particle count is low)
        if num_to_spawn == 0:
            if not audio_reactive:
                # Steady spawn rate to keep the fountain/rain active
                if active_count < max_particles and random.random() < 0.30:
                    num_to_spawn = random.randint(1, 2)
            else:
                # Audio reactive but silent - spawn rarely to keep it alive
                if active_count < 3 and random.random() < 0.05:
                    num_to_spawn = 1

        if num_to_spawn > 0:
            # Center of bottom row
            start_x = self.cols / 2.0
            start_y = 0.0
            for _ in range(num_to_spawn):
                # Shooting angle (80 to 100 degrees)
                angle = (90 + random.uniform(-15, 15)) * pi / 180.0
                
                # Speed: if audio reactive, scale with audio; if auto, use a nice default speed range
                if audio_reactive and audio_level > 0.15:
                    speed = audio_level * 2.8
                else:
                    speed = random.uniform(1.2, 2.5)
                
                if color_mode < 0:
                    p_id = random.randint(0, 3)
                else:
                    p_id = color_mode
                
                self.spawn_fountain_particle(start_x, start_y, angle, speed, p_id, max_particles)

        # Update physics and render
        cols = self.cols
        rows = self.rows
        n_leds = self.n_leds
        idx_map = self._idx_map
        
        for i in range(max_particles):
            idx = i * 6
            if particles[idx + 5] == 1.0:
                px = particles[idx]
                py = particles[idx + 1]
                vx = particles[idx + 2]
                vy = particles[idx + 3]
                life = particles[idx + 4]
                p_palette = palettes[i]

                # Euler physics integration
                px += vx + scaled_wind
                py += vy
                vy -= gravity

                # Bounce off floor (bottom row)
                if py <= 0.0:
                    py = 0.0
                    vy = -vy * bounce
                    if abs(vy) < 0.2 * scale_y:
                        particles[idx + 5] = 0.0
                        continue

                # Boundary check (allow particles to fly higher off-screen before deactivating)
                if px < -2.0 or px > float(cols + 1) or py > float(rows * 2.0):
                    particles[idx + 5] = 0.0
                    continue

                # Age decay
                life -= decay_rate
                if life <= 0.0:
                    particles[idx + 5] = 0.0
                    continue

                particles[idx] = px
                particles[idx + 1] = py
                particles[idx + 2] = vx
                particles[idx + 3] = vy
                particles[idx + 4] = life

                # Comet tail orientation
                flip_x = -1 if vx > 0 else 1
                flip_y = 1 if vy < 0 else -1
                use_horizontal_tail = abs(vx) > abs(vy)

                # Base color mutation
                life_int = int(life * 255)
                c_start, c_end = self._get_fountain_palette(p_palette)

                base_r = c_end[0] + (((c_start[0] - c_end[0]) * life_int) >> 8)
                base_g = c_end[1] + (((c_start[1] - c_end[1]) * life_int) >> 8)
                base_b = c_end[2] + (((c_start[2] - c_end[2]) * life_int) >> 8)

                # Render comet head and tail section
                for dx, dy, shape_intensity in _SHAPE_COMET:
                    if use_horizontal_tail:
                        tx = int(px) + dy * flip_x
                        ty = int(py) + dx * flip_y
                    else:
                        tx = int(px) + dx * flip_x
                        ty = int(py) + dy * flip_y

                    if 0 <= tx < cols and 0 <= ty < rows:
                        r_pix = (base_r * shape_intensity) >> 8
                        g_pix = (base_g * shape_intensity) >> 8
                        b_pix = (base_b * shape_intensity) >> 8

                        map_idx = ty * cols + tx
                        led_idx = idx_map[map_idx]
                        if 0 <= led_idx < n_leds:
                            old_r, old_g, old_b = self.aled[led_idx]
                            new_r = min(255, old_r + r_pix)
                            new_g = min(255, old_g + g_pix)
                            new_b = min(255, old_b + b_pix)
                            self.aled[led_idx] = (new_r, new_g, new_b)

        self.update()

EFFECT_PARAMS = {
    'render_analog_clock': ('show_marks', 'h_width', 'm_width', 's_width', 'target_brightness', 'auto_brightness'),
    'render_auto': (),
    'render_bars': ('orientation', 'bar_size', 'spacing', 'start_row', 'visible_bands', 'reverse_bands', 'direction', 'show_peaks', 'enable_ghosting', 'ghosting_factor', 'enable_symmetric', 'enable_peak_flash', 'peak_flash_threshold', 'center_offset'),
    'render_beat_flash': ('threshold',),
    'render_beat_impact': (),
    'render_black_hole': ('gravity', 'swallow_radius', 'particle_count'),
    'render_blocks': ('threshold',),
    'render_bpm_pulse': (),
    'render_center_split': ('max_height', 'center_offset', 'show_peaks', 'enable_ghosting', 'ghosting_factor', 'enable_peak_flash'),
    'render_classic': ('direction', 'max_height', 'start_row', 'show_peaks', 'enable_ghosting', 'ghosting_factor', 'enable_peak_flash', 'peak_flash_threshold', 'gain'),
    'render_dna_spiral': ('scroll_speed', 'cycles', 'rung_spacing', 'enable_ghosting', 'ghosting_factor', 'audio_reactive'),
    'render_energy_bars': (),
    'render_fast_bars': ('scale',),
    'render_fireworks': ('sparks_per_burst', 'gravity', 'min_interval', 'audio_reactive'),
    'render_gradient_energy': (),
    'render_gravity_bounce': (),
    'render_gravity_cascade': ('gravity', 'wind', 'bounce'),
    'render_gravity_orbiters': ('gravity', 'friction', 'n_orbiters'),
    'render_gravity_well': (),
    'render_gravity_fountain': ('gravity', 'bounce', 'wind', 'color_mode', 'decay_rate', 'max_particles', 'enable_ghosting', 'ghosting_factor', 'audio_reactive'),
    'render_motion_patterns': ('pattern', 'color_mode', 'motion', 'speed', 'direction', 'segment_len', 'spacing', 'bg_brightness', 'audio_reactive', 'palette_shift_speed', 'color1', 'color2'),
    'render_orbital_dots': ('n_dots', 'ring', 'direction', 'speed', 'colors', 'mode', 'ghosting', 'trail', 'audio_reactive', 'pulse', 'dot_mode', 'color'),
    'render_particle_attractor': ('mass', 'particles', 'size', 'friction', 'color_by_age', 'move_attractor', 'swallow', 'ghosting'),
    'render_pendulum_audio': (),
    'render_planet_orbit': ('gravity', 'speed', 'planet_count'),
    'render_plasma_audio': ('speed', 'intensity'),
    'render_presence_bloom': (),
    'render_ps_fire': ('cooling', 'sparking', 'audio_reactive', 'speed'),
    'render_pulse': ('color',),
    'render_quantum_rift': (),
    'render_radial_audio': ('start_row',),
    'render_rain': ('start_row', 'fall_speed'),
    'render_rotating': ('hue_offset',),
    'render_sparkles': ('sparkle_count', 'enable_ghosting', 'ghosting_factor'),
    'render_spectrum': ('hue_offset',),
    'render_spectrum1': (),
    'render_spectrum_matrix': (),
    'render_spiral_audio': ('rotation_speed', 'arms', 'enable_ghosting', 'ghosting_factor'),
    'render_spring_balls': (),
    'render_static_bars': ('start_positions', 'heights', 'color_p', 'color_s', 'color_t', 'color_q', 'columns', 'rainbow', 'color_mode', 'target_brightness', 'auto_brightness', 'color_interval_ms', 'height', 'pos', 'hue_p', 'hue_s', 'hue_t', 'hue_q', 'pos_0', 'pos_1', 'pos_2', 'pos_3', 'height_0', 'height_1', 'height_2', 'height_3'),
    'render_tunnel': (),
    'render_vibrant_lights': (),
    'render_waterfall': (),
    'render_wave_audio': ('wave_height', 'start_row'),
    'colored_snake': ('num_snakes', 'colors', 'bg_color', 'min_len', 'max_len', 'delay', 'directions'),
    'render_sandclock': ('speed', 'color_p', 'y_min', 'y_max', 'half'),
}

def matrix_service(ae_list, mode='auto', **kwargs):
    # Remove 'desc' if present to avoid unexpected keyword argument errors
    kwargs.pop('desc', None)
    
    def call_method_safe(method_name, method, **kwargs_to_pass):
        if method_name in EFFECT_PARAMS:
            valid_args = EFFECT_PARAMS[method_name]
            filtered = {k: v for k, v in kwargs_to_pass.items() if k in valid_args}
        else:
            filtered = kwargs_to_pass
        method(**filtered)
    
    render_name = 'render_' + mode
    for ae in ae_list:
        method = getattr(ae, render_name, None)
        if method is not None:
            call_method_safe(render_name, method, **kwargs)
            continue
            
        method = getattr(ae, mode, None)
        if method is not None:
            call_method_safe(mode, method, **kwargs)
            continue
            
        fallback = getattr(ae, 'render_2d_fx', None)
        if fallback is not None:
            fallback(mode=mode, **kwargs)


def main():
    from init import Controller
    c = Controller()
    c.configure_audio(512, 12, 0.93, 0.99, 0.20, 0.00001, 0.0003)
    c.gamma_table = c.generate_gamma_table(2.4)

    ae2 = AudioEffects(c, c.led2, rows=138, cols=4)
    ae1 = AudioEffects(c, c.led1, rows=19, cols=19)

    if c.audio_ready():
        c.clear_audio_ready()

    import json
    try:
        with open("scenarios.json", "r") as f:
            SCENARIOS_DATA = json.load(f)
    except Exception as e:
        print("Error loading scenarios.json:", e)
        SCENARIOS_DATA = []

    SCENARIOS_COUNT = len(SCENARIOS_DATA)

    def get_scenario(idx):
        if idx < 0 or idx >= SCENARIOS_COUNT:
            return None
        return SCENARIOS_DATA[idx]

    scenario_idx = SCENARIOS_COUNT - 79
    last_switch = time.ticks_ms()
    SCENARIO_DURATION = 15000

    print("\n--- Starting Hyper-Optimized 2D Showcase ---")

    while True:
        now = time.ticks_ms()
        if time.ticks_diff(now, last_switch) > SCENARIO_DURATION:
            scenario_idx = (scenario_idx + 1) % SCENARIOS_COUNT
            last_switch = now
            p = get_scenario(scenario_idx)
            print(f"\n[SCENARIO {scenario_idx+1}/{SCENARIOS_COUNT}]: {p['desc']}")
            
            ae1.reset_effect_state()
            ae2.reset_effect_state()
            ae1.clear_sequence()
            ae2.clear_sequence()
            ae1.clear_particles()
            ae2.clear_particles()
            ae1.update()
            ae2.update()
            c.led1.aled_object.write()
            c.led2.aled_object.write()

        p = get_scenario(scenario_idx)
        matrix_service([ae1, ae2], **p)

        c.led2.aled_object.write()
        c.led1.aled_object.write()

        if c.audio_ready():
            c.clear_audio_ready()

if __name__ == '__main__':
    main()
