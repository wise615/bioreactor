'''

import time
import machine
import math
import uasyncio as asyncio
import os
import numpy as np 
from pico_i2c_lcd import I2cLcd

# Calibration constants
PATH_LENGTH_CM = 1.0       
ABSORBANCE_CONSTANT = 1.0  
ABSORBANCE_OFFSET = 0.0    

# Hardware constants
I2C_ADDR = 0x3F
PIN_SDA = 0
PIN_SCL = 1
PIN_OPT = 26
PIN_LED = 2
PIN_BTN = 3

class Bioreactor: 
    def __init__(self):
        try: 
            self.i2c = machine.I2C(0, sda=machine.Pin(PIN_SDA), scl=machine.Pin(PIN_SCL), freq=400000)
            self.lcd = I2cLcd(self.i2c, I2C_ADDR, 2, 16)
            self.lcd.clear()
            self.lcd.backlight_on()
        except OSError:
            print("CRITICAL: LCD not found. Check I2C wiring.")
            self.lcd = None
        
        # OD Sensor
        self.opt_sensor = machine.ADC(PIN_OPT)
        self.led = machine.Pin(PIN_LED, machine.Pin.OUT)
        self.button = machine.Pin(PIN_BTN, machine.Pin.IN, machine.Pin.PULL_DOWN)
        self.blank_value = 0.0
        self.is_blanked = False
        self.history = []
        self.smoothing_window = 5
        self.filename = "growth_data.csv" # Edit in future to take input
        self._init_csv(append=True)
        self.file = None
    
    def _init_csv(self, append=True):
        mode = "a" if append else "w"
        
        if mode == "w":
            with open(self.filename, mode) as file:
                file.write("Uptime(s),Raw_Signal,Calibrated_OD\n")
        else:
            try:
                os.stat(self.filename)
            except OSError:
                with open(self.filename, "w") as file:
                    file.write("Uptime(s),Raw_Signal,Calibrated_OD\n") # Create headers in first row in new file
        
        
        try:
            with open(self.filename, "w") as file:
                file.write("Uptime(s),Raw_Signal,Calibrated_OD\n")
        except OSError:
            print("CRITICAL: Could not create CSV file.")
            self.file = None

'''

# Master Library
from lib.motor import Motor
from lib.sensors import PHSensor, ODSensor
import time

class Bioreactor:
    def __init__(self):
        self.motors = {}
        self.sensors = {}
        self.claimed_pins = {} # Registry to prevent pin collisions
        self.start_time = time.ticks_ms()
        print("Bioreactor system core initialized. Awaiting hardware setup...")

    def _claim_pins(self, component_name, pins):
        """Internal helper to check for and register pin assignments."""
        for pin in pins:
            if pin in self.claimed_pins:
                conflict = self.claimed_pins[pin]
                print(f"CRITICAL WARNING: Pin {pin} for '{component_name}' is already in use by '{conflict}'!")
                print(f"-> Please check your wiring and setup code. Hardware may behave erratically.")
            else:
                self.claimed_pins[pin] = component_name

    # --- Initialization Methods ---
    def add_motor(self, name, pwm_pin, in1_pin, in2_pin):
        name = str(name).upper()
        if name in self.motors:
            print(f"WARNING: Motor '{name}' is already initialized. Overwriting.")
            
        self._claim_pins(f"Motor {name}", [pwm_pin, in1_pin, in2_pin])
        self.motors[name] = Motor(name, pwm_pin, in1_pin, in2_pin)
        print(f"-> Connected Motor '{name}' on pins ({pwm_pin}, {in1_pin}, {in2_pin})")

    def init_ph_sensor(self, adc_pin=28):
        self._claim_pins("pH Sensor", [adc_pin])
        self.sensors["ph"] = PHSensor(adc_pin=adc_pin)
        print(f"-> Connected pH Sensor on pin {adc_pin}")

    def init_od_sensor(self, adc_pin=26, led_pin=21):
        self._claim_pins("OD Sensor", [adc_pin, led_pin])
        self.sensors["od"] = ODSensor(adc_pin=adc_pin, led_pin=led_pin)
        print(f"-> Connected OD Sensor on ADC pin {adc_pin}, LED pin {led_pin}")

    # --- Safe Operational Methods ---
    def set_motor(self, name, speed_pct, direction="forward"):
        name = str(name).upper()
        if name in self.motors:
            self.motors[name].drive(speed_pct, direction)
        else:
            print(f"STATE ERROR: Command sent to Motor '{name}', but it hasn't been initialized via add_motor().")

    def stop_all_motors(self):
        print("Executing Emergency Motor Stop...")
        for motor in self.motors.values():
            motor.stop()

    def read_ph(self, temperature_c=25.0):
        if "ph" in self.sensors:
            return self.sensors["ph"].read_ph(temperature_c)
        else:
            print("STATE ERROR: Attempted to read pH, but sensor wasn't initialized via init_ph_sensor().")
            return None
            
    def read_od(self):
        if "od" in self.sensors:
            return self.sensors["od"].read_od()
        else:
            print("STATE ERROR: Attempted to read OD, but sensor wasn't initialized via init_od_sensor().")
            return None
            
    def check_health(self):
        """A quick diagnostic to print which systems and pins are currently active."""
        print("\n--- Bioreactor Diagnostic ---")
        print(f"Motors Active: {list(self.motors.keys()) if self.motors else 'None'}")
        print(f"Sensors Active: {list(self.sensors.keys()) if self.sensors else 'None'}")
        print(f"Claimed Pins: {self.claimed_pins}")
        print("-----------------------------\n")