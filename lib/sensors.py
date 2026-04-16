from machine import ADC, Pin
import time
import math
try:
    import ujson as json
except ImportError:
    import json

class PHSensor:
    def __init__(self, adc_pin=28, vref=3.3, cal_file="ph_cal.json"):
        self.vref = vref
        self.cal_file = cal_file
        self._slope_25c = None
        self._intercept = None
        
        try:
            self.adc = ADC(Pin(adc_pin))
            self._load_calibration()
        except ValueError:
            print(f"HARDWARE ERROR (pH Sensor): Pin {adc_pin} does not support ADC.")
            self.adc = None

    def read_voltage(self, samples=20, delay_ms=10):
        if not self.adc:
            return None
        try:
            total = 0
            for _ in range(max(1, samples)): # Prevent range(0)
                total += self.adc.read_u16()
                time.sleep_ms(delay_ms)
            return ((total / samples) / 65535.0) * float(self.vref)
        except Exception as e:
            print(f"ERROR reading pH voltage: {e}")
            return None

    def read_ph(self, temperature_c=25.0, samples=20):
        if self._slope_25c is None or self._intercept is None:
            print("WARNING (pH Sensor): Missing calibration. Run .calibrate() first.")
            return None

        v = self.read_voltage(samples)
        if v is None:
            return None

        try:
            T_k = float(temperature_c) + 273.15
            slope_T = self._slope_25c * (T_k / 298.15)
            ph = slope_T * v + self._intercept
            
            if ph < 0 or ph > 14:
                print(f"WARNING (pH Sensor): Abnormal pH reading ({ph:.2f}). Check probe or recalibrate.")
            return ph
        except Exception as e:
            print(f"ERROR calculating pH: {e}")
            return None

    def _load_calibration(self):
        try:
            with open(self.cal_file, "r") as f:
                data = json.load(f)
            self._slope_25c = float(data["slope_25c"])
            self._intercept = float(data["intercept"])
        except OSError:
            print(f"INFO (pH Sensor): No calibration file '{self.cal_file}' found.")
        except (ValueError, KeyError) as e:
            print(f"ERROR (pH Sensor): Corrupt calibration file. {e}")

    # (Keep the calibrate() function from the previous step)


class ODSensor:
    def __init__(self, adc_pin=26, led_pin=21, blank_file="od_blank.txt"):
        self.blank_file = blank_file
        self.S0 = None
        
        try:
            self.adc = ADC(Pin(adc_pin))
            self.led = Pin(led_pin, Pin.OUT)
            self.S0 = self._load_blank()
        except ValueError:
            print(f"HARDWARE ERROR (OD Sensor): Invalid pin mapping ({adc_pin}, {led_pin}).")
            self.adc = None

    def _read_signal(self, samples=20, delay_ms=5):
        if not self.adc: return None
        try:
            return sum(self.adc.read_u16() for _ in range(max(1, samples))) / samples
        except Exception as e:
            print(f"ERROR reading OD signal: {e}")
            return None

    def _load_blank(self):
        try:
            with open(self.blank_file, "r") as f:
                return float(f.read().strip())
        except OSError:
            print(f"INFO (OD Sensor): No blank file '{self.blank_file}' found.")
            return None
        except ValueError:
            print(f"ERROR (OD Sensor): Corrupt blank file '{self.blank_file}'.")
            return None

    def blank(self):
        if not self.adc: return None
        try:
            self.led.on()
            time.sleep(0.2)
            self.S0 = self._read_signal()
            with open(self.blank_file, "w") as f:
                f.write(f"{self.S0:.6f}")
            self.led.off()
            print(f"SUCCESS: OD Blank saved (S0 = {self.S0:.1f})")
            return self.S0
        except Exception as e:
            print(f"ERROR blanking OD sensor: {e}")
            self.led.off()
            return None

    def read_od(self, leave_led_on=False):
        if self.S0 is None:
            print("WARNING (OD Sensor): Cannot read OD. Run .blank() first.")
            return None
            
        try:
            self.led.on()
            time.sleep(0.1)
            S = self._read_signal()
            if not leave_led_on:
                self.led.off()

            if S is None or S <= 0:
                print("WARNING (OD Sensor): Signal dropped to 0. Is the LED broken or blocked?")
                return None
                
            od = math.log10(self.S0 / S)
            return max(0.0, od) # Prevent negative ODs due to minor noise
            
        except Exception as e:
            print(f"ERROR calculating OD: {e}")
            self.led.off()
            return None