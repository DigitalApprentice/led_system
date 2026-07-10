import uctypes
from machine import bitstream, Pin
import micropython

black = (0, 0, 0)

class AledsRgb:

    ORDER_RGB  = (0, 1, 2)
    ORDER_RBG  = (0, 2, 1)
    ORDER_GRB  = (1, 0, 2)
    ORDER_GBR  = (2, 0, 1)
    ORDER_BRG  = (1, 2, 0)
    ORDER_BGR  = (2, 1, 0)

    TIMING_800KHZ = (400, 850, 800, 450)
    TIMING_400KHZ = (800, 1700, 1600, 900)

    TYPE_WS2812 = 'ws2812'

    def __init__(self, pin, buffer, n, bpp=3, order=ORDER_RGB,
                 timing=TIMING_800KHZ, led_type='ws2812'):
        self.pin      = Pin(pin, Pin.OUT)
        self.n        = n
        self.bpp      = bpp
        self.led_type = led_type.lower()
        self.timing   = timing
        self.order = order
        self._order_buf = bytearray(order)
        self._tmp       = bytearray(bpp)
        self.set_buffer(buffer)

    def set_buffer(self, buffer):
        self.aled_buffer = buffer

    # ── __setitem__ / __getitem__ ────────────────────────────────────────────

    def __setitem__(self, i, color):
        if i < 0 or i >= self.n:
            raise IndexError("LED index out of range")
        self._set_led_rgb(i, color[0], color[1], color[2])

    @micropython.viper
    def _set_led_rgb(self, i: int, c0: int, c1: int, c2: int):
        buf  = ptr8(self.aled_buffer)
        o    = ptr8(self._order_buf)
        base: int = i * 3
        buf[base + o[0]] = c0
        buf[base + o[1]] = c1
        buf[base + o[2]] = c2

    @micropython.viper
    def _read_led(self, i: int):
        bpp: int = int(self.bpp)
        buf  = ptr8(self.aled_buffer)
        o    = ptr8(self._order_buf)
        tmp  = ptr8(self._tmp)
        base: int = i * bpp
        tmp[o[0]] = buf[base]
        tmp[o[1]] = buf[base + 1]
        tmp[o[2]] = buf[base + 2]
        if bpp == 4:
            tmp[o[3]] = buf[base + 3]

    def __getitem__(self, i):
        if i < 0 or i >= self.n:
            raise IndexError(f"LED index {i} out of range [0, {self.n})")
        self._read_led(i)
        return tuple(self._tmp)

    def __len__(self):
        return self.n

    # ── brightness / gamma ───────────────────────────────────────────────────

    @micropython.viper
    def _calc_brightness_to_tmp_rgb(self, r: int, g: int, b: int, bv: int):
        tmp    = ptr8(self._tmp)
        tmp[0] = (r * bv) >> 8
        tmp[1] = (g * bv) >> 8
        tmp[2] = (b * bv) >> 8

    def change_brightness(self, color, brightness):
        """Returns color scaled by brightness (0-255)."""
        if brightness <= 0:
            return (0,0,0)
        if brightness >= 255:
            return color
        self._calc_brightness_to_tmp_rgb(color[0], color[1], color[2], brightness)
        return tuple(self._tmp)

    @micropython.viper
    def apply_brightness_to_buffer(self, brightness: int):
        """Scale every byte in buffer by brightness (0-255)."""
        p_buf: ptr8 = ptr8(self.aled_buffer)
        length: int = int(len(self.aled_buffer))
        b: int = brightness
        for i in range(length):
            p_buf[i] = (int(p_buf[i]) * b) >> 8

    @micropython.viper
    def _apply_gamma_to_tmp_rgb(self, r: int, g: int, b: int,
                                brightness: int, gamma_table):
        p_gamma = ptr8(gamma_table)
        tmp = ptr8(self._tmp)
        b_corr: int = int(p_gamma[brightness])
        tmp[0] = (r * b_corr) >> 8
        tmp[1] = (g * b_corr) >> 8
        tmp[2] = (b * b_corr) >> 8

    def apply_gamma(self, color, brightness, gamma_table):
        self._apply_gamma_to_tmp_rgb(color[0], color[1], color[2], brightness, gamma_table)
        return tuple(self._tmp)

    @micropython.viper
    def apply_br_to_buffer(self, gamma_table, brightness: int):
        p_buf:   ptr8 = ptr8(self.aled_buffer)
        p_gamma: ptr8 = ptr8(gamma_table)
        b_corr: int   = int(p_gamma[brightness])
        length: int   = int(len(self.aled_buffer))
        for i in range(length):
            p_buf[i] = (int(p_buf[i]) * b_corr) >> 8

    @micropython.viper
    def apply_br_per_pixel(self, gamma, buffer, modulator):
        p_buf: ptr8 = ptr8(buffer)
        p_mod: ptr8 = ptr8(modulator)
        p_gamma: ptr8 = ptr8(gamma)
        num_pixels: int = int(len(modulator))

        for i in range(num_pixels):
            idx: int = i * 3
            b_corr: int = int(p_gamma[int(p_mod[i])])
            p_buf[idx] = (int(p_buf[idx]) * b_corr) >> 8
            p_buf[idx + 1] = (int(p_buf[idx + 1]) * b_corr) >> 8
            p_buf[idx + 2] = (int(p_buf[idx + 2]) * b_corr) >> 8

    # ── fill / clear ─────────────────────────────────────────────────────────

    @micropython.viper
    def clear(self):
        buf32 = ptr32(self.aled_buffer)
        buf8  = ptr8(self.aled_buffer)
        total: int = int(self.n) * int(self.bpp)
        words: int = total >> 2
        for i in range(words):
            buf32[i] = 0
        tail_start: int = words << 2
        if tail_start < total:
            for i in range(tail_start, total):
                buf8[i] = 0

    @micropython.viper
    def aled_fast_fill(self, ba: ptr32, ba_len: int, value: int):
        for i in range(ba_len):
            ba[i] = value

    def aled_fill(self, color):
        """Fill entire strip with one color (with color order conversion)."""
        o = self._order_buf
        self._aled_fill_rgb(color[o[0]], color[o[1]], color[o[2]])

    @micropython.viper
    def _aled_fill_rgb(self, c0: int, c1: int, c2: int):
        buf  = ptr8(self.aled_buffer)
        n: int = int(self.n)
        i: int = 0
        while i < n:
            idx: int   = i * 3
            buf[idx]   = c0
            buf[idx+1] = c1
            buf[idx+2] = c2
            i += 1

    def set_all(self, color, brightness=255):
        o = self._order_buf
        self._set_all_rgb(color[o[0]], color[o[1]], color[o[2]], brightness)

    @micropython.viper
    def _set_all_rgb(self, c0: int, c1: int, c2: int, bv: int):
        buf = ptr8(self.aled_buffer)
        n: int = int(self.n)
        r: int = (c0 * bv) >> 8
        g: int = (c1 * bv) >> 8
        b: int = (c2 * bv) >> 8
        i: int = 0
        while i < n:
            idx: int = i * 3
            buf[idx] = r
            buf[idx + 1] = g
            buf[idx + 2] = b
            i += 1
    # ── gradient / segment ───────────────────────────────────────────────────

    def fast_gradient(self, color1, color2):
        """Gradient fill from color1 to color2."""
        o = self._order_buf
        self._aled_fast_gradient_rgb(
                self.aled_buffer, self.n,
                color1[o[0]], color1[o[1]], color1[o[2]],
                color2[o[0]], color2[o[1]], color2[o[2]])

    @micropython.viper
    def _aled_fast_gradient_rgb(self, ba: ptr8, n_leds: int,
                                 r1: int, g1: int, b1: int,
                                 r2: int, g2: int, b2: int):
        idx: int       = 0
        i: int         = 0
        n_minus_1: int = n_leds - 1
        if n_minus_1 <= 0:
            n_minus_1 = 1
        while i < n_leds:
            t: int     = (i * 256) // n_minus_1
            ba[idx]    = r1 + (((r2 - r1) * t) >> 8)
            ba[idx+1]  = g1 + (((g2 - g1) * t) >> 8)
            ba[idx+2]  = b1 + (((b2 - b1) * t) >> 8)
            idx += 3
            i   += 1

    def fast_fill_segment(self, start, end, color):
        """Fast fill segment [start, end) with color."""
        if start < 0 or end > self.n or start >= end:
            raise ValueError(f"Invalid segment: start={start}, end={end}, n={self.n}")
        o = self._order_buf
        self._aled_fast_fill_segment_rgb(self.aled_buffer, start, end, color[o[0]], color[o[1]], color[o[2]])

    @micropython.viper
    def _aled_fast_fill_segment_rgb(self, ba: ptr8, start: int, end: int,
                                     r: int, g: int, b: int):
        idx: int     = start * 3
        end_idx: int = end * 3
        while idx < end_idx:
            ba[idx]   = r
            ba[idx+1] = g
            ba[idx+2] = b
            idx += 3
    # ── output ───────────────────────────────────────────────────────────────

    def write(self):
        bitstream(self.pin, 0, self.timing, self.aled_buffer)

    def round_coordinates(self, coordinates):
        return [(int(x + 0.5), int(y + 0.5)) for x, y in coordinates]
