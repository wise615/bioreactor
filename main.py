from bioreactor import Bioreactor
import time

# 1. Create the system
my_reactor = Bioreactor()

# 2. Hardware Setup
# Using explicit variable names makes the pin assignments clear
my_reactor.add_motor(name="Acid_Pump", pwm_pin=15, in1_pin=14, in2_pin=13)
my_reactor.add_motor(name="Agitator", pwm_pin=10, in1_pin=11, in2_pin=12)

my_reactor.init_ph_sensor(adc_pin=28)
my_reactor.init_od_sensor(adc_pin=26, led_pin=21)

# Quick diagnostic check before running the main loop
my_reactor.check_health()

# 3. Continuous Control Loop
print("Starting control loop... Press Ctrl+C to stop.")

try:
    while True:
        # Read the sensors
        current_ph = my_reactor.read_ph()
        current_od = my_reactor.read_od()
        
        # --- TROUBLESHOOTING FAIL-SAFE ---
        # Always verify the reading is not None before doing math or logic!
        # If a wire unplugs, this prevents a TypeError crash.
        if current_ph is not None:
            
            # Print valid readings to the Thonny shell
            print(f"pH: {current_ph:.2f}")
            
            # Simple control logic
            if current_ph > 7.5:
                my_reactor.set_motor("Acid_Pump", speed_pct=30, direction="forward")
            else:
                my_reactor.set_motor("Acid_Pump", speed_pct=0)
                
        else:
            print("Skipping pump logic: Invalid pH reading. Check wiring/calibration.")
            my_reactor.set_motor("Acid_Pump", speed_pct=0) # Safe default state
            
        
        # Keep the agitator running constantly
        my_reactor.set_motor("Agitator", speed_pct=40)
            
        # --- THONNY SERIAL FAIL-SAFE ---
        # Mandatory delay to prevent USB serial flooding and Thonny freezing
        time.sleep(1.0) 

except KeyboardInterrupt:
    # Safely shut down all hardware if the student hits "Stop" in Thonny
    my_reactor.stop_all_motors()
    print("System safely shut down.")