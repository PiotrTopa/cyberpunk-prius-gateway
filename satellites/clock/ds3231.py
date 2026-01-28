from machine import I2C

class DS3231:
    _ADDR = 0x68
    
    def __init__(self, i2c):
        self.i2c = i2c
    
    def _bcd2dec(self, bcd):
        return (((bcd & 0xf0) >> 4) * 10 + (bcd & 0x0f))
    
    def _dec2bcd(self, dec):
        return ((dec // 10) << 4) + (dec % 10)
    
    def get_time(self):
        """
        Returns (year, month, day, hour, minute, second)
        """
        try:
            data = self.i2c.readfrom_mem(self._ADDR, 0x00, 7)
            ss = self._bcd2dec(data[0])
            mm = self._bcd2dec(data[1])
            hh = self._bcd2dec(data[2])
            wday = self._bcd2dec(data[3])
            dd = self._bcd2dec(data[4])
            mon = self._bcd2dec(data[5] & 0x1F)
            yy = self._bcd2dec(data[6])
            return (2000 + yy, mon, dd, hh, mm, ss)
        except Exception as e:
            print(f"DS3231 Read Error: {e}")
            return None

    def set_time(self, year, month, day, hour, minute, second):
        """
        Sets the time. Year should be full (e.g. 2024).
        """
        try:
            yy = year % 100
            data = bytearray(7)
            data[0] = self._dec2bcd(second)
            data[1] = self._dec2bcd(minute)
            data[2] = self._dec2bcd(hour)
            data[3] = self._dec2bcd(0) # Weekday ignored for now
            data[4] = self._dec2bcd(day)
            data[5] = self._dec2bcd(month)
            data[6] = self._dec2bcd(yy)
            self.i2c.writeto_mem(self._ADDR, 0x00, data)
            print(f"DS3231 Time set to: {year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}")
        except Exception as e:
            print(f"DS3231 Write Error: {e}")

    def get_temperature(self):
        """
        Reads temperature from DS3231.
        Returns float in Celsius.
        """
        try:
            data = self.i2c.readfrom_mem(self._ADDR, 0x11, 2)
            msb = data[0]
            lsb = data[1]
            # Integer part is MSB (signed, but usually positive indoors)
            # Fractional part is top 2 bits of LSB * 0.25
            temp = msb + ((lsb >> 6) * 0.25)
            return temp
        except Exception:
            return 0.0
