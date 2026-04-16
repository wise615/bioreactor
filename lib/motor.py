from machine import Pin, PWM
import time

class Motor:
    def __init__(self, name, pwm_pin, in1_pin, in2_pin, pwm_freq=100000):
        self.name = name
        self.current_speed = 0
        self.current_dir = "stopped"
        
        try:
            self.pwm = PWM(Pin(pwm_pin))
            self.pwm.freq(pwm_freq)
            self.in1 = Pin(in1_pin, Pin.OUT)
            self.in2 = Pin(in2_pin, Pin.OUT)
            self.stop()
        except ValueError as e:
            print(f"HARDWARE ERROR ({self.name}): Invalid pin configuration. {e}")
        except Exception as e:
            print(f"UNEXPECTED ERROR initializing {self.name}: {e}")

    def _clamp_pct(self, p):
        if p < 0:
            print(f"WARNING ({self.name}): Speed {p}% is below 0. Clamping to 0.")
            return 0
        if p > 100:
            print(f"WARNING ({self.name}): Speed {p}% is above 100. Clamping to 100.")
            return 100
        return p

    def drive(self, speed_pct, direction="forward", duration_s=None):
        try:
            self.current_speed = self._clamp_pct(speed_pct)
            self.current_dir = str(direction).lower()
            duty = int((self.current_speed / 100) * 65535)
            
            self.pwm.duty_u16(duty)
            
            if self.current_dir == "forward":
                self.in1.value(1)
                self.in2.value(0)
            elif self.current_dir == "backward":
                self.in1.value(0)
                self.in2.value(1)
            else:
                print(f"WARNING ({self.name}): Unknown direction '{direction}'. Defaulting to stop.")
                self.stop()
                return

            if duration_s is not None:
                time.sleep(max(0, duration_s)) # Prevent negative sleep times
                self.stop()
                
        except AttributeError:
            print(f"CRITICAL ({self.name}): Cannot drive. Hardware failed to initialize.")
        except Exception as e:
            print(f"ERROR driving {self.name}: {e}")

    def stop(self):
        try:
            self.pwm.duty_u16(0)
            self.in1.value(0)
            self.in2.value(0)
            self.current_speed = 0
            self.current_dir = "stopped"
        except AttributeError:
            pass # Fails silently if initialization failed