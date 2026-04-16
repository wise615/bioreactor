# ==============================================================================
# 1-LITER BIOREACTOR CONTINUOUS OD PROBE MASTER CODE
# ==============================================================================

# --- BUILT-IN MICROPYTHON LIBRARIES ---
# 'machine' is the most important MicroPython library. It is the direct equivalent 
# of Arduino's core hardware functions (pinMode, digitalWrite, analogRead). 
# It lets Python talk directly to the silicon pins on the Pico 2W.
import machine

# 'math' provides standard mathematical functions (like log10 for our OD calculation).
import math

# 'time' handles hardware-level timing. In MicroPython, we use specific functions 
# like time.ticks_ms() instead of standard Python time functions to track milliseconds 
# precisely, much like Arduino's millis().
import time

# 'uasyncio' is MicroPython's "micro" version of Python's asynchronous I/O library.
# Instead of pausing the whole chip with a delay(), asyncio lets us say:
# "Pause this specific function and go do other things, then come back in 1 second."
# This is how we read the button while waiting for the LED to warm up.
import uasyncio as asyncio

# 'os' handles the operating system interface. On a Pico, the "OS" is just a tiny 
# file system on the flash memory chip. We use it to create and manage the CSV file.
import os

# --- EXTERNAL LIBRARIES ---
# This imports the specific I2cLcd class from the pico_i2c_lcd.py driver file 
# that you will save directly onto the Pico alongside this main.py script.
from pico_i2c_lcd import I2cLcd

# --- CALIBRATION CONSTANTS ---
# We define these at the top so students don't have to hunt through the logic 
# when calibrating their individual bioreactors.
PATH_LENGTH_CM = 1.0       
ABSORBANCE_CONSTANT = 1.0  
ABSORBANCE_OFFSET = 0.0    

# --- HARDWARE CONSTANTS ---
I2C_ADDR = 0x3F
PIN_SDA = 0
PIN_SCL = 1
PIN_OPT = 26
PIN_LED = 2
PIN_BTN = 3

# In Python, a 'class' is a blueprint. Think of it like a CAD assembly file. 
# It groups all the physical parts (pins, sensors) and functions into one single object.
class ContinuousODProbe:
    
    # __init__ is the Python constructor. It acts exactly like void setup() in C++.
    # It runs once the moment you turn the system on. 
    # 'self' is required in Python classes. It is the equivalent of 'this->' in C++,
    # meaning "belonging to this specific object."
    def __init__(self):
        
        # We use a try/except block. If a student wires the I2C screen incorrectly,
        # the Pico will throw an OSError. Instead of crashing the whole program,
        # we catch the error, print a warning, and keep running the sensor.
        try:
            # machine.I2C sets up the communication bus. '0' is the Pico's I2C hardware block 0.
            self.i2c = machine.I2C(0, sda=machine.Pin(PIN_SDA), scl=machine.Pin(PIN_SCL), freq=400000)
            
            # Instantiate the LCD screen object using the bus we just created.
            self.lcd = I2cLcd(self.i2c, I2C_ADDR, 2, 16)
            self.lcd.clear()
            self.lcd.backlight_on()
        except OSError:
            print("CRITICAL: LCD not found. Check I2C wiring.")
            self.lcd = None 

        # machine.ADC creates an Analog-to-Digital Converter object for the OPT101.
        self.opt_sensor = machine.ADC(PIN_OPT)
        
        # machine.Pin sets up digital pins. machine.Pin.OUT is like pinMode(LED, OUTPUT).
        self.led = machine.Pin(PIN_LED, machine.Pin.OUT)
        
        # machine.Pin.IN is pinMode(BTN, INPUT). 
        # machine.Pin.PULL_DOWN activates the Pico's internal pulldown resistor,
        # keeping the pin at 0V until the student physically presses the button to send 3.3V.
        self.button = machine.Pin(PIN_BTN, machine.Pin.IN, machine.Pin.PULL_DOWN)
        
        # Initialize internal variables that will store our data (replacing global variables).
        self.blank_value = 0.0
        self.is_blanked = False
        
        # self.history is a Python list (array) that will hold recent readings for smoothing.
        self.history = []         
        self.smoothing_window = 5 
        
        # Set up the data logging file.
        self.filename = "growth_data.csv"
        self._init_csv(append=True)
        
        # time.ticks_ms() grabs the Pico's internal hardware millisecond counter.
        # We save this start time so we can calculate elapsed uptime later.
        self.start_time = time.ticks_ms() 

    # The underscore before the name indicates this is a "private" helper function.
    def _init_csv(self, append=True):
        
        # If we are wiping the file, we open it in "w" (write) mode, which destroys old data.
        # If we are keeping data, we open it in "a" (append) mode.
        mode = "a" if append else "w"
        
        if mode == "w":
            # The 'with open(...)' syntax automatically safely closes the file when done.
            with open(self.filename, mode) as file:
                file.write("Uptime(s),Raw_Signal,Calibrated_OD\n")
        else:
            try:
                # os.stat asks the file system for file details. 
                # If the file doesn't exist, it throws an OSError.
                os.stat(self.filename)
            except OSError:
                # Catch the error, meaning the file is missing, so we create it and add headers.
                with open(self.filename, "w") as file:
                    file.write("Uptime(s),Raw_Signal,Calibrated_OD\n")

    # Takes the calculated data and writes it directly to the flash memory.
    def log_data(self, uptime_sec, raw_signal, calibrated_od):
        try:
            with open(self.filename, "a") as file:
                # :.4f formats the floating-point number to exactly 4 decimal places.
                file.write(f"{uptime_sec},{raw_signal},{calibrated_od:.4f}\n")
            return True # Return True so the UI knows the save was successful.
        except OSError:
            return False 

    # Calculates how long the bioreactor has been running since boot or reset.
    def get_uptime_string(self):
        # time.ticks_diff safely subtracts timestamps, preventing errors when the 
        # hardware millisecond counter rolls over back to 0 after a few days.
        elapsed_ms = time.ticks_diff(time.ticks_ms(), self.start_time)
        
        # // is integer division (e.g., 5000 // 1000 = 5 seconds)
        total_seconds = elapsed_ms // 1000
        hours = total_seconds // 3600
        
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        # :02d formats the integers to always have 2 digits (e.g., "05" instead of "5").
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}", total_seconds

    # A safe wrapper to update the screen only if it was successfully connected.
    def update_lcd(self, line1, line2):
        if self.lcd:
            self.lcd.move_to(0, 0)
            
            # :<16 forces the string to take up exactly 16 characters by adding 
            # spaces to the right. This erases old characters without screen flickering.
            self.lcd.putstr(f"{line1:<16}")
            self.lcd.move_to(0, 1)
            self.lcd.putstr(f"{line2:<16}")

    # 'async def' defines a coroutine. It tells Python that this function contains 
    # tasks that will take time, and it should let other functions run while it waits.
    async def get_transmission(self, samples=10):
        
        # A nested helper function to avoid writing the same average loop twice.
        async def _read_adc_average():
            total = 0
            for _ in range(samples):
                # 'await' hands control back to the main Pico processor for 100ms.
                # Unlike time.sleep(), the Pico can check button presses during this wait.
                await asyncio.sleep_ms(100) 
                try:
                    # read_u16() reads the analog pin and returns a 16-bit integer (0-65535).
                    total += self.opt_sensor.read_u16()
                except OSError:
                    pass 
            return total / samples if samples > 0 else 0

        # 1. Take Dark Reading (LED off)
        # .value(0) pulls the digital pin to 0 Volts.
        self.led.value(0)
        dark_signal = await _read_adc_average()
        
        # 2. Take Light Reading (LED on)
        # .value(1) pushes the digital pin to 3.3 Volts.
        self.led.value(1)
        
        # Wait 1 full second for the LED semiconductor to thermally stabilize.
        await asyncio.sleep_ms(1000) 
        light_signal = await _read_adc_average()
        
        self.led.value(0)
        await asyncio.sleep_ms(1000)
        
        # Return the absolute difference to isolate the biological signal from room light.
        return abs(light_signal - dark_signal)

    # The 10-second startup sequence where the student can press the button to calibrate.
    async def run_calibration_sequence(self):
        countdown = 10
        for _ in range(10):
            # .value() reads the digital pin state. 1 means the button is pressed (HIGH).
            if self.button.value() == 1:
                self.update_lcd("Blanking...", "Please wait.")
                
                # Await the transmission function to get the baseline value.
                self.blank_value = await self.get_transmission()
                self.is_blanked = True
                break
            
            self.update_lcd(f"Start in: {countdown}", "Press for blank!")
            countdown -= 1
            await asyncio.sleep_ms(1000)

    # This is the equivalent of void loop() in C++. It runs forever.
    async def monitor(self):
        # Run the initial calibration window.
        await self.run_calibration_sequence()
        
        # Reset the timer immediately after calibration finishes.
        self.start_time = time.ticks_ms() 
        
        while True:
            # --- 5-SECOND RESET LOGIC ---
            # If the student presses the button during the normal monitoring loop...
            if self.button.value() == 1:
                press_start = time.ticks_ms()
                reset_triggered = False
                
                # ...trap them in this inner loop as long as they hold the button down.
                while self.button.value() == 1:
                    held_duration = time.ticks_diff(time.ticks_ms(), press_start)
                    seconds_left = 5 - (held_duration // 1000)
                    
                    if seconds_left > 0:
                        self.update_lcd("Hold to Reset", f"Restart in: {seconds_left}s")
                    
                    # If they hit 5000 milliseconds, trip the flag and break out of the loop.
                    if held_duration >= 5000:
                        reset_triggered = True
                        break 
                        
                    await asyncio.sleep_ms(100) 
                
                # If the flag was tripped, execute the full system wipe.
                if reset_triggered:
                    self.update_lcd("Resetting...", "Clearing Data")
                    self._init_csv(append=False) 
                    self.is_blanked = False
                    self.blank_value = 0.0
                    
                    # .clear() empties the Python list holding the moving average data.
                    self.history.clear()
                    
                    await asyncio.sleep_ms(1500) 
                    await self.run_calibration_sequence()
                    self.start_time = time.ticks_ms() 
                    
                    # 'continue' skips the rest of the current while loop iteration 
                    # and starts back at the top.
                    continue 

            # --- STANDARD MONITORING LOGIC ---
            # Grab the raw hardware reading.
            raw_transmission = await self.get_transmission()
            
            # .append() adds the newest reading to the end of our list.
            self.history.append(raw_transmission)
            
            # If the list has more than 5 items, .pop(0) deletes the oldest one.
            # This creates a rolling "window" of the 5 most recent data points.
            if len(self.history) > self.smoothing_window:
                self.history.pop(0)
                
            # sum() adds all list values; len() counts them. This calculates the average.
            smoothed_transmission = sum(self.history) / len(self.history)
            
            # Grab the formatted uptime strings.
            uptime_str, uptime_sec = self.get_uptime_string()
            
            # Default fallback values in case calibration was skipped.
            display_od = "ERR"
            log_od = 0.0
            
            if self.is_blanked and self.blank_value > 0:
                ratio = smoothed_transmission / self.blank_value
                if ratio > 0:
                    # Apply Beer-Lambert Logarithmic Math
                    raw_od = -math.log10(ratio)
                    
                    # Apply standard curve calibration (y = mx + b)
                    log_od = (raw_od / PATH_LENGTH_CM) * ABSORBANCE_CONSTANT + ABSORBANCE_OFFSET
                    display_od = f"{log_od:.3f} OD"
            
            # Try to save to flash memory, and return True/False based on success.
            log_success = self.log_data(uptime_sec, smoothed_transmission, log_od)
            log_icon = "*" if log_success else "!" 
            
            # Update the LCD
            if self.is_blanked:
                self.update_lcd(f"OD: {display_od}", f"T:{uptime_str} [{log_icon}]")
            else:
                self.update_lcd(f"Raw: {int(smoothed_transmission)}", f"T:{uptime_str} [{log_icon}]")
            
            # Print to the Thonny serial monitor for debugging.
            print(f"Uptime: {uptime_str} | Raw: {smoothed_transmission:.1f} | OD: {display_od} | Logged: {log_success}")
            
            # Yield control back to the Pico hardware manager for a moment.
            await asyncio.sleep_ms(100) 

# --- EXECUTION ---
if __name__ == '__main__':
    probe = ContinuousODProbe()
    
    try:
        # We hand the monitor loop over to asyncio.run(). This creates the master 
        # event loop that juggles the hardware timers and the sleep functions.
        asyncio.run(probe.monitor())
        
    except KeyboardInterrupt:
        # If the student hits the 'Stop' button in Thonny, it throws a KeyboardInterrupt.
        # We catch it to safely turn off the LED so it doesn't overheat the sample,
        # and clear the screen before exiting.
        probe.led.value(0)
        if probe.lcd:
            probe.lcd.clear()
        print("\nProbe stopped safely.")