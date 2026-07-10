import random
import time
import micropython
from math import sin, cos, floor, sqrt, pi

class EffectsHelpers:
    @staticmethod
    def random_factor(_random_factor):
        return random.random() <= _random_factor

    def elapsed_time(self, last_time, limit, time_return=False):
        """Check elapsed time."""
        elapsed = time.ticks_diff(time.ticks_ms(), last_time)
        if time_return is False:
            return elapsed >= limit
        return elapsed

    @staticmethod
    def lerp(a, b, t):
        return a + (b - a) * t

    @staticmethod
    def smoothstep(edge0, edge1, x):
        try:
            x = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
        except:
            x = max(0.0, min(1.0, (x - edge0)))
        return x * x * (3 - 2 * x)

    @staticmethod
    def check_beat(val, threshold, peak=None):
        """Returns True if value exceeds threshold (normalized by peak if provided)."""
        if peak and peak > 0:
            return (val / peak) > threshold
        return val > threshold

    def _pal_color(self, idx):
        """Get RGB tuple from controller palette by index. Assumes host sets self.c
        (controller), self.pal_len, and self.aled (bpp) - see AudioEffects."""
        if self.pal_len > 0 and self.c.palette:
            i = (int(idx) % self.pal_len) * self.aled.bpp
            return (self.c.palette[i], self.c.palette[i + 1], self.c.palette[i + 2])
        return (255, 255, 255)

    # Backward-compatible alias (old name used by color_return/get_short_palette callers elsewhere)
    _get_pal_color = _pal_color

    @micropython.native
    def _pal_rgb(self, pi, val, gb):
        pal = self.c.palette
        return (
            ((pal[pi] * val) >> 8) * gb >> 8,
            ((pal[pi+1] * val) >> 8) * gb >> 8,
            ((pal[pi+2] * val) >> 8) * gb >> 8
        )

    @micropython.native
    def _norm(self, val):
        return max(0.0, min(1.0, float(val) / 255.0))

    def color_return(self, color, color_step=1, color_offset=0, gamma=False):
        if color is None:
            return (0, 0, 0)
        elif isinstance(color, tuple):
            return color
        elif isinstance(color, list):
            if len(color) >= 3:
                return (color[0], color[1], color[2])
            return (0, 0, 0)
        elif isinstance(color, int):
            return self._pal_color(color + color_offset)
        elif isinstance(color, str):
            if color in ('R', 'RG'):
                self.calculate_pal_offset(color_step)
                return self._pal_color(self.direction * (self.pal_offset + color_offset))
            elif color == 'RM':
                return self._pal_color(random.randint(0, self.pal_length - 1))
            elif color == 'S':
                # Simplified for modular use; assumes base has sequence
                idx = color_offset % self.segment_length
                return self._get_pixel(idx)
        return (0, 0, 0)

    def calculate_pal_offset(self, color_step=0):
        if color_step == 0:
            base = self.pal_length // max(1, self.segment_length)
            self.pal_step = max(1, base)
        else:
            self.pal_step = max(1, int(color_step))
        self.pal_offset = (self.pal_offset + self.pal_step) % self.pal_length

    def color_from_colormode(self, color_p, color_s, color_t, color_mode, section_no, section_length, offset, counter, direction):
        color1 = self.color_return(color_p)
        color2 = self.color_return(color_s)
        color3 = self.color_return(color_t)
        if color_mode == 0:
            return color1
        elif color_mode == 1:
            return color1 if direction == 1 else color2
        elif color_mode == 2:
            return color1 if section_no & 1 != 0 else color2
        elif color_mode == 3:
            return [color1, color2, color3][counter % 3]
        elif color_mode == 4:
            return self.color_return(counter * section_length + offset)
        elif color_mode == 5:
            return self.color_blend(color1, color2, random.randrange(65, 192, 8))
        elif color_mode == 6:
            return self.color_add(color1, self._pal_color(random.randint(0, self.pal_length - 1)))
        return color1

    def color_blend(self, color1, color2, blend=127):
        if blend == 0: return color1
        if blend >= 255: return color2
        r1, g1, b1 = color1
        r2, g2, b2 = color2
        r = ((r2 * blend) + (r1 * (255 - blend))) >> 8
        g = ((g2 * blend) + (g1 * (255 - blend))) >> 8
        b = ((b2 * blend) + (b1 * (255 - blend))) >> 8
        return (r, g, b)

    def color_add(self, color1, color2):
        r = color1[0] + color2[0]
        g = color1[1] + color2[1]
        b = color1[2] + color2[2]
        maximum = max(r, g, b)
        if maximum < 256:
            return (r, g, b)
        return (int(r * 255 / maximum), int(g * 255 / maximum), int(b * 255 / maximum))

    def color_multiply(self, color, factor):
        return (int(color[0] * factor), int(color[1] * factor), int(color[2] * factor))

    def set_palette(self, palette=0, gamma=True, gradient=False, length=None):
        # The Controller now manages the palette.
        # We delegate to its internal set_palette if needed.
        if hasattr(self.controller, 'set_palette'):
            self.controller.set_palette(length if length else 256)

    def get_short_palette(self, base_color=0, palette_type='PRIMARY'):
        # Fallback short palettes since cl_palettes is deprecated.
        # We can extract representative colors from the current controller palette.
        try:
            return [self._pal_color(base_color), 
                    self._pal_color(base_color + 85), 
                    self._pal_color(base_color + 170)]
        except:
            return [(255, 0, 0), (0, 255, 0), (0, 0, 255)]

    @staticmethod
    def _hsv_to_rgb(h, s, v):
        # h: 0-255, s: 0-255, v: 0-255
        if s == 0:
            return v, v, v
        
        region = h // 43
        remainder = (h - (region * 43)) * 6
        
        p = (v * (255 - s)) >> 8
        q = (v * (255 - ((s * remainder) >> 8))) >> 8
        t = (v * (255 - ((s * (255 - remainder)) >> 8))) >> 8
        
        if region == 0:
            return v, t, p
        elif region == 1:
            return q, v, p
        elif region == 2:
            return p, v, t
        elif region == 3:
            return p, q, v
        elif region == 4:
            return t, p, v
        else:
            return v, p, q

    @staticmethod
    def _rgb_to_hsv(r, g, b):
        mx = r if r > g else g
        mx = mx if mx > b else b
        mn = r if r < g else g
        mn = mn if mn < b else b
        df = mx - mn
        
        v = mx
        s = 0 if mx == 0 else (255 * df) // mx
        
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
        h = (h * 255) // 360
        return h, s, v

    def _get_harmonized_colors(self, mode, base_hue):
        # Generates two harmonized RGB colors based on mode and base_hue (0-255)
        if mode == 'complementary':
            h1 = base_hue
            h2 = (base_hue + 128) % 256
            c1 = self._hsv_to_rgb(h1, 255, 255)
            c2 = self._hsv_to_rgb(h2, 255, 255)
        elif mode == 'pal_complementary':
            c1 = self._pal_color(base_hue)
            c2 = self._pal_color(base_hue + self.pal_len // 2)
        elif mode in ('pal_similar', 'similar', 'analogous'):
            c1 = self._pal_color(base_hue)
            c2 = self._pal_color(base_hue + self.pal_len // 12)
        elif mode == 'triadic':
            h1 = base_hue
            h2 = (base_hue + 85) % 256
            c1 = self._hsv_to_rgb(h1, 255, 255)
            c2 = self._hsv_to_rgb(h2, 255, 255)
        elif mode == 'monochromatic':
            c1 = self._hsv_to_rgb(base_hue, 255, 255)
            c2 = self._hsv_to_rgb(base_hue, 128, 160)
        elif mode == 'sunset':
            h1 = (base_hue // 4) % 30
            h2 = ((base_hue // 4) % 30 + 220) % 256
            c1 = self._hsv_to_rgb(h1, 255, 255)
            c2 = self._hsv_to_rgb(h2, 255, 255)
        elif mode == 'ocean':
            h1 = (120 + (base_hue // 4) % 40) % 256
            h2 = (160 + (base_hue // 4) % 30) % 256
            c1 = self._hsv_to_rgb(h1, 255, 255)
            c2 = self._hsv_to_rgb(h2, 255, 255)
        elif mode == 'forest':
            h1 = (60 + (base_hue // 4) % 40) % 256
            h2 = (30 + (base_hue // 4) % 25) % 256
            c1 = self._hsv_to_rgb(h1, 255, 255)
            c2 = self._hsv_to_rgb(h2, 255, 255)
        elif mode == 'lava':
            h1 = (base_hue // 8) % 15
            h2 = (15 + (base_hue // 8) % 20) % 256
            c1 = self._hsv_to_rgb(h1, 255, 255)
            c2 = self._hsv_to_rgb(h2, 255, 255)
        elif mode == 'neon':
            h1 = (200 + (base_hue // 2) % 40) % 256
            h2 = (80 + (base_hue // 2) % 40) % 256
            c1 = self._hsv_to_rgb(h1, 255, 255)
            c2 = self._hsv_to_rgb(h2, 255, 255)
        elif mode == 'rainbow':
            c1 = self._hsv_to_rgb(base_hue, 255, 255)
            c2 = self._hsv_to_rgb((base_hue + 40) % 256, 255, 255)
        elif mode == 'random':
            h1 = base_hue
            h2 = (h1 + 60 + (base_hue % 130)) % 256
            c1 = self._hsv_to_rgb(h1, 255, 255)
            c2 = self._hsv_to_rgb(h2, 255, 255)
        else:
            c1 = self._pal_color(base_hue)
            c2 = self._pal_color(base_hue + self.pal_len // 3)
        return c1, c2

    def _resolve_motion_colors(self, color_mode, color1, color2, hue):
        """Extracts color parsing and harmony logic from render_motion_patterns."""
        c1, c2 = None, None
        
        if isinstance(color_mode, (list, tuple)):
            if len(color_mode) == 3 and isinstance(color_mode[0], int):
                color1 = color_mode
            elif len(color_mode) >= 2 and isinstance(color_mode[0], (list, tuple)):
                color1 = color_mode[0]
                color2 = color_mode[1]
            elif len(color_mode) == 1 and isinstance(color_mode[0], (list, tuple)):
                color1 = color_mode[0]
        
        if color1 is not None and color2 is not None:
            c1 = color1
            c2 = color2
        elif color1 is not None:
            c1 = color1
            mode_str = color_mode if isinstance(color_mode, str) else 'complementary'
            h, s, v = self._rgb_to_hsv(color1[0], color1[1], color1[2])
            if mode_str == 'complementary':
                c2 = self._hsv_to_rgb((h + 128) % 256, s, v)
            elif mode_str in ('analogous', 'similar', 'pal_similar'):
                c2 = self._hsv_to_rgb((h + 25) % 256, s, v)
            elif mode_str == 'triadic':
                c2 = self._hsv_to_rgb((h + 85) % 256, s, v)
            elif mode_str == 'monochromatic':
                c2 = self._hsv_to_rgb(h, max(40, s // 2), max(40, (v * 150) // 256))
            elif mode_str == 'sunset':
                c2 = self._hsv_to_rgb((h + 40) % 256, s, v)
            elif mode_str == 'ocean':
                c2 = self._hsv_to_rgb((h + 30) % 256, s, v)
            elif mode_str == 'lava':
                c2 = self._hsv_to_rgb((h + 15) % 256, s, v)
            elif mode_str == 'forest':
                c2 = self._hsv_to_rgb((h - 20) % 256, s, v)
            elif mode_str == 'neon':
                c2 = self._hsv_to_rgb((h + 100) % 256, s, v)
            else:
                c2 = self._hsv_to_rgb((h + 128) % 256, s, v)
        
        if c1 is None or c2 is None:
            if color1 is not None:
                c1 = color1
            if color2 is not None:
                c2 = color2
                
            if c1 is None or c2 is None:
                if c1 is not None and c2 is None:
                    h, s, v = self._rgb_to_hsv(c1[0], c1[1], c1[2])
                    c2 = self._hsv_to_rgb((h + 128) % 256, s, v)
                elif c2 is not None and c1 is None:
                    h, s, v = self._rgb_to_hsv(c2[0], c2[1], c2[2])
                    c1 = self._hsv_to_rgb((h + 128) % 256, s, v)
                else:
                    c1, c2 = self._get_harmonized_colors(color_mode, int(hue))
        return c1, c2

