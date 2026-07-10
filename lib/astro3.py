import math, struct

def to_f32(x): return struct.unpack('f', struct.pack('f', x))[0]

def _julian_day(year, month, day):
    if month <= 2: year -= 1; month += 12
    a = year // 100
    b = 2 - a + (a // 4)
    return int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + b - 1524.5

def _sunrise_sunset_FIXED(year, month, day, latitude, longitude, sunrise=True, use_f32=False):
    f = to_f32 if use_f32 else (lambda x: x)
    jd = f(_julian_day(year, month, day))
    n = f(f(jd) - f(2451545.0) + f(0.0008))
    j_star = f(n - f(longitude / f(360.0)))
    m = f((f(357.5291) + f(0.98560028) * j_star) % f(360.0))
    m_rad = f(math.radians(m))
    c = f(f(1.9148)*math.sin(m_rad) + f(0.0200)*math.sin(f(2)*m_rad) + f(0.0003)*math.sin(f(3)*m_rad))
    lamb = f((f(m + c + f(102.9372)) + f(180.0)) % f(360.0))
    lamb_rad = f(math.radians(lamb))
    transit_corr = f(f(0.0053)*math.sin(m_rad) - f(0.0069)*math.sin(f(2)*lamb_rad))
    sin_delta = f(math.sin(lamb_rad) * math.sin(math.radians(f(23.44))))
    delta = f(math.asin(sin_delta))
    lat_rad = f(math.radians(latitude))
    cos_omega = f((f(math.sin(math.radians(f(-0.83)))) - math.sin(lat_rad)*math.sin(delta)) / (math.cos(lat_rad)*math.cos(delta)))
    if cos_omega < -1.0 or cos_omega > 1.0: return (0, False)
    omega = f(math.degrees(math.acos(cos_omega)))
    day_offset = f(f(-longitude / f(360.0)) + f(0.0008) + transit_corr)
    if sunrise: day_offset = f(day_offset - f(omega / f(360.0)))
    else:       day_offset = f(day_offset + f(omega / f(360.0)))
    minutes_utc = f((day_offset + f(0.5)) * f(1440.0)) % f(1440.0)
    return (minutes_utc, True)

LAT, LON = 51.177361, 17.000250
tests = [(2026,5,7,'May 7 2026'), (2026,1,15,'Jan 15 2026'), (2026,12,21,'Dec 21 2026')]
for y,mo,d,label in tests:
    sr64, _ = _sunrise_sunset_FIXED(y,mo,d,LAT,LON,True,  False)
    ss64, _ = _sunrise_sunset_FIXED(y,mo,d,LAT,LON,False, False)
    sr32, _ = _sunrise_sunset_FIXED(y,mo,d,LAT,LON,True,  True)
    ss32, _ = _sunrise_sunset_FIXED(y,mo,d,LAT,LON,False, True)
    print(f'{label}:')
    print(f'  64-bit: sunrise={int(sr64):4d} ({int(sr64)//60:02d}:{int(sr64)%60:02d} UTC)  sunset={int(ss64):4d} ({int(ss64)//60:02d}:{int(ss64)%60:02d} UTC)')
    print(f'  32-bit: sunrise={int(sr32):4d} ({int(sr32)//60:02d}:{int(sr32)%60:02d} UTC)  sunset={int(ss32):4d} ({int(ss32)//60:02d}:{int(ss32)%60:02d} UTC)')