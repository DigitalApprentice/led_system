from machine import Pin, I2C
import time

class BH1750:
    """I2C(0, scl=Pin(47), sda=Pin(21), freq=100000)"""
    def __init__(self, i2c, addr=0x23):
        self.i2c = i2c
        self.addr = addr
        try:
            self.i2c.writeto(self.addr, bytes([0x01])) # Power on
        except OSError:
            print(f"BH1750 not found at address {hex(addr)}")
    
    @property
    def luminance(self):
        # Tryb High Resolution (1lx)
        self.i2c.writeto(self.addr, bytes([0x10]))
        data = self.i2c.readfrom(self.addr, 2)
        return (data[0] << 8 | data[1]) / 1.2


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    # Inicjalizacja magistrali
    i2c = I2C(0, scl=Pin(47), sda=Pin(21), freq=100000)

    # Inicjalizacja czujnika z TWOIM adresem
    light_sensor = BH1750(i2c, addr=0x23)

    while True:
        lux = light_sensor.luminance
        print(f"Światło: {lux:.1f} lx")
        time.sleep(1)
