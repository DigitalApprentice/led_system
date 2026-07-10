"""
Optimized switch operations for ESP32-S3 MicroPython
Supports: Button (with debouncing), RotaryEncoder (quadrature), AnalogJoystick (KY-023)

Copyright Tomasz Zgrys (Digital-Apprentice) - 2022-2025 - MIT license
Optimized for ESP32-S3 @ 240MHz with interrupt-driven operations
"""

from machine import Pin, ADC, Timer
import time

# ── Input command constants (int for speed) ──────────────────────
# Cardinal directions shared by joystick, buttons and IR remote.
CMD_NONE   = 0   # No input detected.
CMD_UP     = 1   # Up / plus / increase.
CMD_DOWN   = 2   # Down / minus / decrease.
CMD_LEFT   = 3   # Left / previous / move backward.
CMD_RIGHT  = 4   # Right / next / move forward.
CMD_CENTER = 5  # Joystick centered, no directional deflection.

# Diagonal joystick-only directions. These preserve both axis components.
CMD_UP_RIGHT   = 6   # Joystick pushed up and right at the same time.
CMD_UP_LEFT    = 7   # Joystick pushed up and left at the same time.
CMD_DOWN_RIGHT = 8  # Joystick pushed down and right at the same time.
CMD_DOWN_LEFT  = 9  # Joystick pushed down and left at the same time.


CMD_UP_L      = 11   # Long Up / plus / increase.
CMD_DOWN_L    = 12   # Long Down / minus / decrease.
CMD_LEFT_L    = 13   # Long Left / previous / move backward.
CMD_RIGHT_L   = 14   # Long Right / next / move forward.
CMD_CONFIRM   = 15    # Confirm / Click / Ok.
CMD_CONFIRM_L = 16  # Long Confirm / Click / Ok.

CMD_L1 = 20    # Led1 / Focus on
CMD_L1_L = 21  # Led1 / On-Off
CMD_L2 = 30    # Led2 / Focus on
CMD_L2_L = 31  # Led2 / On-Off

# Global refresh flag for button state changes
button_refresh = None

def b_refresh(state=None):
    """Global button refresh flag (used by external polling loops)"""
    global button_refresh
    if state is not None:
        button_refresh = state
    else:
        return button_refresh


class Button:

    def __init__(self, button_pin, powering='GND', click_interval=200, long_press_time=1500, debounce_time=50):

        self.powering(button_pin, powering)
        self.button_pin.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self._button_handler)
        self._click_interval = click_interval    # time in ms
        self._long_press_time = long_press_time  # time in ms
        self._debounce_ms = debounce_time

        self.pressed = False
        self.released = False
        self._state = 0
        self._last_state = 0

        self._pressing_time = 0
        self._time_of_state = 0
        self._time_of_last_state = 0
        self._time_of_last_clicked = 0

    def _button_handler(self, pin):
        """IRQ handler for button state changes (original version with multi-click fix)"""

        self._button_value = pin.value()
        if self._button_value != self._last_button_value:
            current_time = time.ticks_ms()
            if time.ticks_diff(current_time, self._time_of_last_state) < self._debounce_ms:
                return
            self._time_of_state = current_time
            if self._button_value != self._base_button_value:
                self.pressed = True
                self.released = False
            else:
                self._pressing_time = time.ticks_diff(self._time_of_state, self._time_of_last_state)
                if self.pressed == True:
                    if 25 < self._pressing_time < self._long_press_time:
                        click_interval = time.ticks_diff(self._time_of_state, self._time_of_last_clicked)
                        if self._last_state >= 1 and click_interval < self._click_interval:
                            # FIX: Use _last_state as base instead of +=
                            self._state = self._last_state + 1
                        else:
                            self._state = 1
                        self._last_state = self._state
                        self._time_of_last_clicked = time.ticks_ms()
                    elif self._pressing_time >= self._long_press_time:
                        self._state = -1
                        self._last_state = self._state

                    self.pressed = False
                    self.released = True

            self._time_of_last_state = self._time_of_state
            self._last_button_value = self._button_value
            b_refresh(True)

    def powering(self, button_pin=None, powering=None):
        """Configure or get button powering mode."""
        if button_pin is not None and powering is not None:
            self._powering = powering
            self.button_pin = Pin(button_pin, Pin.IN, Pin.PULL_UP if self._powering == 'GND' else Pin.PULL_DOWN)

            # Base value depends on powering
            if self._powering == 'GND':
                self._base_button_value = 1  # Pulled up, pressed = 0
            else:
                self._base_button_value = 0  # Pulled down, pressed = 1

            self._last_button_value = self._base_button_value
        else:
            return self._powering

    def button_value(self):
        """Get current GPIO pin value."""
        return self.button_pin.value()

    def state_value(self, state=None):
        """
        Get or set button state.

        Returns:
            >0: Number of clicks (1=single, 2=double, etc.)
            -1: Long press
            0: No action

        Set to 0 after handling to clear state.
        """
        if state is None:
            return self._state
        else:
            self._state = state

    def is_pressed(self):
        """Check if button is currently pressed."""
        return self.pressed

    def is_released(self):
        """Check if button is currently released."""
        return self.released

    def click_interval(self, click_interval=None):
        """Get or set click interval (ms)."""
        if click_interval is None:
            return self._click_interval
        else:
            self._click_interval = click_interval

    def long_press_time(self, long_press_time=None):
        """Get or set long press time (ms)."""
        if long_press_time is None:
            return self._long_press_time
        else:
            self._long_press_time = long_press_time

    def clear_button_state(self):
        """Clear button state (same as state_value(0))."""
        self._state = 0

class RotaryEncoder(Button):
    def __init__(self, pin_A, pin_B, switch_pin=None, powering='GND', step=1, direction='CW', debounce_time=5):

        self._debounce_time = debounce_time
        self._last_irq_time = 0

        # Initialize encoder pins
        self.pin_A = Pin(pin_A, Pin.IN, Pin.PULL_UP if powering == 'GND' else Pin.PULL_DOWN)
        self.pin_B = Pin(pin_B, Pin.IN, Pin.PULL_UP if powering == 'GND' else Pin.PULL_DOWN)

        # Quadrature state tracking (Gray code)
        self._last_state = (self.pin_A.value() << 1) | self.pin_B.value()
        self._encoder_value = 0

        # Setup step and direction
        self._base_step = abs(step)
        self._direction = direction
        self._step = self._base_step if direction == 'CW' else -self._base_step

        # State transition index_table for quadrature decoding (Gray code)
        # [old_state][new_state] = direction (1=CW, -1=CCW, 0=invalid/noise)
        self._transition_table = [
            [ 0, -1,  1,  0],  # 00 -> 00, 01, 10, 11
            [ 1,  0,  0, -1],  # 01 -> 00, 01, 10, 11
            [-1,  0,  0,  1],  # 10 -> 00, 01, 10, 11
            [ 0,  1, -1,  0]   # 11 -> 00, 01, 10, 11
        ]

        # Enable IRQs on both pins for full quadrature
        self.pin_A.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self._encoder_handler)
        self.pin_B.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self._encoder_handler)

        # Initialize button if switch_pin provided
        if switch_pin is not None:
            super().__init__(switch_pin, powering, debounce_time=50)

    def _encoder_handler(self, pin):
        """
        Optimized quadrature decoder with Gray code state machine.

        Uses 4-state transition index_table for reliable direction detection.
        Debounces encoder signals to prevent noise-induced errors.
        """
        current_time = time.ticks_ms()

        # DEBOUNCING: Ignore rapid transitions (encoder noise/bouncing)
        if time.ticks_diff(current_time, self._last_irq_time) < self._debounce_time:
            return

        self._last_irq_time = current_time

        # Read current quadrature state (2-bit Gray code)
        current_state = (self.pin_A.value() << 1) | self.pin_B.value()

        # Look up transition direction in index_table
        direction = self._transition_table[self._last_state][current_state]

        # Update encoder value based on direction
        if direction != 0:
            self._encoder_value += direction * self._base_step

        # Save state for next transition
        self._last_state = current_state

    def value(self, value=None):
        """Get or set encoder value."""
        if value is None:
            return self._encoder_value
        else:
            self._encoder_value = value

    def step(self, step=None):
        """Get or set step value (always positive)."""
        if step is None:
            return self._base_step
        else:
            self._base_step = abs(step)
            self._step = self._base_step if self._direction == 'CW' else -self._base_step

    def direction(self, direction=None):
        """Get or set rotation direction ('CW' or 'CCW')."""
        if direction is None:
            return self._direction
        else:
            if direction in ('CW', 'CCW'):
                self._direction = direction
                self._step = self._base_step if direction == 'CW' else -self._base_step
            else:
                self._direction = 'CW'
                self._step = self._base_step


class AnalogJoystick(Button):

    def __init__(self, pin_X, pin_Y, switch_pin, powering='GND',
                 sample_rate=20, dead_zone=10, click_interval=200, long_press_time=1500):

        # Initialize button (SW) via parent class
        super().__init__(switch_pin, powering, click_interval, long_press_time)

        # Initialize ADC for analog axes
        self.adc_x = ADC(Pin(pin_X))
        self.adc_y = ADC(Pin(pin_Y))

        # Configure ADC attenuation (0-3.3V range)
        # ADC.ATTN_11DB = 0-3.3V (full range for KY-023)
        self.adc_x.atten(ADC.ATTN_11DB)
        self.adc_y.atten(ADC.ATTN_11DB)

        # ADC width (12-bit = 0-4095)
        self.adc_x.width(ADC.WIDTH_12BIT)
        self.adc_y.width(ADC.WIDTH_12BIT)

        # Calibration values (center position)
        self._center_x = 2048  # Mid-range default (12-bit)
        self._center_y = 2048
        self._calibrated = False

        # Dead zone (percentage of full range)
        self._dead_zone = dead_zone
        self._dead_zone_raw = int(4096 * dead_zone / 100)

        # Current position
        self._raw_x = 2048
        self._raw_y = 2048
        self._pos_x = 0  # Normalized position (-100 to +100)
        self._pos_y = 0
        self._direction = CMD_CENTER

        # Timer for periodic ADC sampling
        self._sample_period_ms = int(1000 / sample_rate)
        self._timer = Timer(1)
        self._timer.init(period=self._sample_period_ms, mode=Timer.PERIODIC,
                        callback=self._sample_callback)

    def _sample_callback(self, timer):

        # Read raw ADC values
        self._raw_x = self.adc_x.read()
        self._raw_y = self.adc_y.read()

        # Apply calibration offset
        offset_x = self._raw_x - self._center_x
        offset_y = self._raw_y - self._center_y

        # Apply dead zone
        if abs(offset_x) < self._dead_zone_raw:
            offset_x = 0
        if abs(offset_y) < self._dead_zone_raw:
            offset_y = 0

        # Normalize to -100 to +100 range
        max_range = 2048 - self._dead_zone_raw
        if max_range > 0:
            self._pos_x = int((offset_x / max_range) * 100)
            self._pos_y = -int((offset_y / max_range) * 100)  # NEGACJA - joystick ma odwróconą oś Y

            # Clamp to valid range
            self._pos_x = max(-100, min(100, self._pos_x))
            self._pos_y = max(-100, min(100, self._pos_y))
        else:
            self._pos_x = 0
            self._pos_y = 0

        # Update direction (8 directions + center)
        self._update_direction()

    def _update_direction(self):

        threshold = 30  # Minimum deflection to register direction (%)

        if abs(self._pos_x) < threshold and abs(self._pos_y) < threshold:
            self._direction = CMD_CENTER
        elif abs(self._pos_x) < threshold:
            # Vertical movement
            self._direction = CMD_UP if self._pos_y > 0 else CMD_DOWN
        elif abs(self._pos_y) < threshold:
            # Horizontal movement
            self._direction = CMD_RIGHT if self._pos_x > 0 else CMD_LEFT
        else:
            # Diagonal movement
            if self._pos_x > 0:
                self._direction = CMD_UP_RIGHT if self._pos_y > 0 else CMD_DOWN_RIGHT
            else:
                self._direction = CMD_UP_LEFT if self._pos_y > 0 else CMD_DOWN_LEFT

    def calibrate(self, samples=10):

        sum_x = 0
        sum_y = 0

        for _ in range(samples):
            sum_x += self.adc_x.read()
            sum_y += self.adc_y.read()
            time.sleep_ms(10)

        self._center_x = sum_x // samples
        self._center_y = sum_y // samples
        self._calibrated = True

        return (self._center_x, self._center_y)

    def get_raw(self):
        """
        Get raw ADC values.

        Returns:
            (x, y): Raw ADC values (0-4095)
        """
        return (self._raw_x, self._raw_y)

    def get_position(self):

        return (self._pos_x, self._pos_y)

    def get_direction(self):

        return self._direction

    def set_dead_zone(self, dead_zone):
        """
        Set dead zone percentage (0-100).

        Args:
            dead_zone: Dead zone radius in % (0=no dead zone, 100=full range)
        """
        self._dead_zone = max(0, min(100, dead_zone))
        self._dead_zone_raw = int(4096 * self._dead_zone / 100)

    def get_dead_zone(self):
        """Get current dead zone percentage."""
        return self._dead_zone

    def is_calibrated(self):
        """Check if joystick has been calibrated."""
        return self._calibrated

    def stop(self):
        """Stop ADC sampling timer."""
        self._timer.deinit()

    def start(self):
        """Start/restart ADC sampling timer."""
        self._timer.init(period=self._sample_period_ms, mode=Timer.PERIODIC,
                        callback=self._sample_callback)
