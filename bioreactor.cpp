#include <Arduino.h>
#include <FS.h>
#include <SD_MMC.h>
#include <math.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// ============================================================
// 0. USER CONFIGURATION
// ============================================================
const float RUN_DURATION_HOURS = 168.0;
const bool USE_PH_PROBE   = true;
const bool USE_DO_PROBE   = true;
const bool USE_OD_PROBE   = true;
const bool USE_TEMP_PROBE = true;

// ============================================================
// 1. PIN DEFINITIONS
// ============================================================
#define PIN_BUTTON      19 // Safe from bootloop

#define PIN_TEMP_SENSOR 33
#define PIN_RELAY       26 // Safe from SD conflict

#define PIN_OD_ADC      34
#define PIN_OD_LED      32
#define PIN_PH_ADC      35
#define PIN_DO_ADC      39 // VN Pin

#define PIN_OLED_SDA    21
#define PIN_OLED_SCL    22
#define SCREEN_WIDTH    128
#define SCREEN_HEIGHT   64
#define OLED_RESET      -1

#define PIN_MOT_A_PWM   27 // Safe from SD conflict
#define PIN_MOT_B_PWM   25
#define PIN_MOT_C_PWM   18
#define PIN_MOT_D_PWM   13 // Added Motor D on unused GPIO 13

// ============================================================
// 2. GLOBAL VARIABLES
// ============================================================
const float TEMP_LOW_THRESHOLD = 28.0;
const float TEMP_HIGH_THRESHOLD = 30.0;
bool heaterOn = false;

OneWire oneWire(PIN_TEMP_SENSOR);
DallasTemperature tempSensors(&oneWire);

#define PH_CAL_FILE "/ph_Calibration.txt"
#define DO_CAL_FILE "/do_Calibration.txt"
#define OD_CAL_FILE "/od_Calibration.txt"

float ph_slope = -5.70;
float ph_intercept = 21.34;
float do_slope = 100.0;
float do_intercept = 0.0;
float od_blank_net = 1.0;
const float MIN_SIGNAL = 0.0001;

const unsigned long LOG_INTERVAL_MS = 60000;
unsigned long lastLogTime = 0;
unsigned long mainLoopTimer = 0;
bool isLogging = false;
char currentFileName[32] = "";

const float DO_LOW_THRESHOLD = 10.0;
const float PH_LOW_THRESHOLD = 6.30;

const unsigned long FEED_PUMP_DURATION_MS = 10000;
const unsigned long BASE_PUMP_DURATION_MS = 5000;
const unsigned long FEED_COOLDOWN_MS = 600000;
const unsigned long BASE_COOLDOWN_MS = 600000;

unsigned long lastFeedTime = 4294967295UL - FEED_COOLDOWN_MS;
unsigned long lastBaseTime = 4294967295UL - BASE_COOLDOWN_MS;

bool feedPumpActive = false;
bool basePumpActive = false;
unsigned long feedPumpStartTime = 0;
unsigned long basePumpStartTime = 0;

// Cumulative counters
unsigned int feedPumpCycles = 0;
unsigned int basePumpCycles = 0;
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// ============================================================
// 3. HELPER & OLED FUNCTIONS
// ============================================================
float readVoltage(int pin, int samples = 50) {
  long total = 0;
  for (int i = 0; i < samples; i++) {
    total += analogRead(pin);
    delay(2);
  }
  float avgAdc = total / (float)samples;
  return (avgAdc / 4095.0) * 3.3;
}

void setupOLED() {
  Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED failed. Try address 0x3D.");
    return;
  }
  display.clearDisplay();
  display.display();
}

void updateOLED(float time_min, float od_val, float ph_val, float do_val, float temp_val) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0, 0);  display.println("Bioreactor Monitor");
  display.setCursor(0, 12); display.print("Time: "); display.print(time_min, 1); display.println(" min");

  display.setCursor(0, 24);
  if (USE_OD_PROBE) { display.print("OD: "); display.print(od_val, 3);
  } 
  else { display.print("OD: OFF "); }

  if (USE_PH_PROBE) { display.print(" | pH: "); display.println(ph_val, 2);
  } 
  else { display.println(" | pH: OFF"); }

  display.setCursor(0, 36);
  if (USE_DO_PROBE) { display.print("DO: "); display.print(do_val, 1);
  display.println("% "); } 
  else { display.println("DO: OFF"); }

  display.setCursor(0, 48);
  if (USE_TEMP_PROBE) { display.print("Temp: "); display.print(temp_val, 1);
  display.println(" C"); } 
  else { display.println("Temp: OFF"); }

  display.setCursor(0, 56); display.print("Log: "); display.print(isLogging ? "ON" : "OFF");
  display.display();
}

// ============================================================
// 4. MOTOR CONTROL
// ============================================================
void runMotor(char motor, int speedPercent) {
  int pwmPin;
  switch (motor) {
    case 'A': pwmPin = PIN_MOT_A_PWM; break;
    case 'B': pwmPin = PIN_MOT_B_PWM; break;
    case 'C': pwmPin = PIN_MOT_C_PWM; break;
    case 'D': pwmPin = PIN_MOT_D_PWM; break; // Added Motor D logic
    default: return;
  }

  int dutyCycle = map(constrain(speedPercent, 0, 100), 0, 100, 0, 255);
  analogWrite(pwmPin, dutyCycle);
}

void stopAllMotors() {
  runMotor('A', 0); runMotor('B', 0); runMotor('C', 0); runMotor('D', 0); // Stops Motor D safely on halt
}

// ============================================================
// 5. CALIBRATION LOAD (WITH SAFETIES)
// ============================================================
void loadSavedCalibrations() {
  bool calibrationMissing = false;
  // Load pH
  if (USE_PH_PROBE) {
    if (SD_MMC.exists(PH_CAL_FILE)) {
      File file = SD_MMC.open(PH_CAL_FILE);
      if (file) {
        ph_slope = file.parseFloat();
        ph_intercept = file.parseFloat();
        file.close();
      }
    } else {
      calibrationMissing = true;
    }
  }

  // Load DO
  if (USE_DO_PROBE) {
    if (SD_MMC.exists(DO_CAL_FILE)) {
      File file = SD_MMC.open(DO_CAL_FILE);
      if (file) {
        do_slope = file.parseFloat();
        do_intercept = file.parseFloat();
        file.close();
      }
    } else {
      calibrationMissing = true;
    }
  }

  // Load OD
  if (USE_OD_PROBE) {
    if (SD_MMC.exists(OD_CAL_FILE)) {
      File file = SD_MMC.open(OD_CAL_FILE);
      if (file) {
        od_blank_net = file.parseFloat();
        file.close();
        if (od_blank_net < MIN_SIGNAL) od_blank_net = MIN_SIGNAL;
      }
    } else {
      calibrationMissing = true;
    }
  }

  // Fail-safe trigger
  if (calibrationMissing) {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);   display.println("ERROR:");
    display.setCursor(0, 16);  display.println("Missing Cal Data!");
    display.setCursor(0, 32);  display.println("Run Calib. Script");
    display.setCursor(0, 48);  display.println("System Halted.");
    display.display();
    Serial.println("CRITICAL ERROR: Calibration files not found. Halting system.");
    while(true) {
      delay(100);
    }
  }
}

// ============================================================
// 6. SENSOR CALCULATIONS & CONTROL
// ============================================================
float calculateOD() {
  if (!USE_OD_PROBE) return 0.0;
  
  // The LED is permanently on. Read the voltage directly.
  float light_v = readVoltage(PIN_OD_ADC);

  float sample_net = light_v; // Assuming minimal ambient light interference
  if (sample_net < MIN_SIGNAL) sample_net = MIN_SIGNAL;
  
  float od_val = -log10(sample_net / od_blank_net);
  if (od_val < 0) od_val = 0.0;
  return od_val;
}

float calculatePH() {
  if (!USE_PH_PROBE) return 0.0;
  return (ph_slope * readVoltage(PIN_PH_ADC)) + ph_intercept;
}

float calculateDO() {
  if (!USE_DO_PROBE) return 0.0;
  return (do_slope * readVoltage(PIN_DO_ADC)) + do_intercept;
}

float readTemperatureC() {
  if (!USE_TEMP_PROBE) return 0.0;
  tempSensors.requestTemperatures();
  return tempSensors.getTempCByIndex(0);
}

void controlPumps(float ph_val, float do_val) {
  unsigned long now = millis();
  if (USE_DO_PROBE && do_val < DO_LOW_THRESHOLD && !feedPumpActive && (now - lastFeedTime >= FEED_COOLDOWN_MS)) {
    runMotor('B', 100);
    feedPumpActive = true; 
    feedPumpStartTime = now; 
    lastFeedTime = now;
    feedPumpCycles++;
    // Increment counter when pump starts
  }
  if (feedPumpActive && (now - feedPumpStartTime >= FEED_PUMP_DURATION_MS)) {
    runMotor('B', 0);
    feedPumpActive = false;
  }
  
  if (USE_PH_PROBE && ph_val < PH_LOW_THRESHOLD && !basePumpActive && (now - lastBaseTime >= BASE_COOLDOWN_MS)) {
    runMotor('C', 100);
    basePumpActive = true; 
    basePumpStartTime = now; 
    lastBaseTime = now;
    basePumpCycles++;
    // Increment counter when pump starts
  }
  if (basePumpActive && (now - basePumpStartTime >= BASE_PUMP_DURATION_MS)) {
    runMotor('C', 0);
    basePumpActive = false;
  }
}

void controlHeater(float tempC) {
  if (!USE_TEMP_PROBE) return;
  if (tempC < TEMP_LOW_THRESHOLD && !heaterOn) {
    digitalWrite(PIN_RELAY, HIGH); heaterOn = true;
  } else if (tempC > TEMP_HIGH_THRESHOLD && heaterOn) {
    digitalWrite(PIN_RELAY, LOW); heaterOn = false;
  }
}

// ============================================================
// 7. LOGGING
// ============================================================
void startNewLogFile() {
  int fileIndex = 1;
  while (true) {
    sprintf(currentFileName, "/data_%03d.csv", fileIndex);
    if (!SD_MMC.exists(currentFileName)) break;
    fileIndex++;
  }
  File file = SD_MMC.open(currentFileName, FILE_WRITE);
  if (file) {
    String header = "Time(min)";
    if (USE_OD_PROBE) header += ",OD";
    if (USE_PH_PROBE) header += ",pH";
    if (USE_DO_PROBE) header += ",DO(%)";
    if (USE_TEMP_PROBE) header += ",Temp(C)";
    // Updated header to reflect cumulative cycles
    header += ",FeedCycles,BaseCycles,Heater";
    
    file.println(header);
    file.close();
    Serial.printf("Logging initialized to: %s\n", currentFileName);
    isLogging = true;
  } else {
    Serial.println("Could not create log file.");
    isLogging = false;
  }
  lastLogTime = 4294967295UL - LOG_INTERVAL_MS;
}

void logData(float time_min, float od_val, float ph_val, float do_val, float temp_val) {
  if (!isLogging) return;
  File file = SD_MMC.open(currentFileName, FILE_APPEND);
  if (file) {
    String dataLine = String(time_min, 2);
    if (USE_OD_PROBE) dataLine += "," + String(od_val, 3);
    if (USE_PH_PROBE) dataLine += "," + String(ph_val, 2);
    if (USE_DO_PROBE) dataLine += "," + String(do_val, 1);
    if (USE_TEMP_PROBE) dataLine += "," + String(temp_val, 2);
    // Log the cumulative counters instead of boolean states
    dataLine += "," + String(feedPumpCycles) + "," + String(basePumpCycles) + "," + String(heaterOn);
    file.println(dataLine);
    file.close();
  }
}

void handleLoggingButton() {
  static bool lastButtonState = HIGH;
  bool currentState = digitalRead(PIN_BUTTON);
  if (currentState == LOW && lastButtonState == HIGH) {
    isLogging = !isLogging;
    Serial.printf("\nDATA LOGGING TOGGLED: %s\n", isLogging ? "ON" : "OFF");
    delay(50);
  }
  lastButtonState = currentState;
}

// ============================================================
// 8. SETUP & LOOP
// ============================================================
void setup() {
  Serial.begin(115200); delay(1000);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_RELAY, OUTPUT); digitalWrite(PIN_RELAY, LOW);
  
  pinMode(PIN_OD_LED, OUTPUT);
  digitalWrite(PIN_OD_LED, HIGH); // Set OD LED on permanently

  pinMode(PIN_MOT_A_PWM, OUTPUT); 
  pinMode(PIN_MOT_B_PWM, OUTPUT); 
  pinMode(PIN_MOT_C_PWM, OUTPUT); 
  pinMode(PIN_MOT_D_PWM, OUTPUT); // Initialize Motor D PWM pin

  stopAllMotors();
  setupOLED();

  if (!SD_MMC.begin("/sdcard", true)) {
    Serial.println("SD Card Mount Failed.");
    isLogging = false;
  } else {
    loadSavedCalibrations();
    startNewLogFile();
  }

  if (USE_TEMP_PROBE) {
    tempSensors.begin();
    tempSensors.setWaitForConversion(true);
  }

  runMotor('A', 100);
  runMotor('D', 30); // Start Motor D permanently at 10% speed
  Serial.println("SYSTEM READY & RUNNING");
}

void loop() {
  float time_min = millis() / 60000.0;
  float time_hours = time_min / 60.0;

  handleLoggingButton();

  if (time_hours >= RUN_DURATION_HOURS) {
    stopAllMotors();
    digitalWrite(PIN_RELAY, LOW);
    isLogging = false;
    updateOLED(time_min, 0, 0, 0, 0);
    delay(1000);
    return;
  }

  if (millis() - mainLoopTimer >= 1000) {
    mainLoopTimer = millis();

    float od_val = calculateOD();
    float ph_val = calculatePH();
    float do_val = calculateDO();
    float tempC = readTemperatureC();

    controlPumps(ph_val, do_val);
    if (USE_TEMP_PROBE) {
      if (tempC == DEVICE_DISCONNECTED_C) {
        digitalWrite(PIN_RELAY, LOW);
        heaterOn = false;
      } else {
        controlHeater(tempC);
      }
    }

    updateOLED(time_min, od_val, ph_val, do_val, tempC);
    if (millis() - lastLogTime >= LOG_INTERVAL_MS) {
      logData(time_min, od_val, ph_val, do_val, tempC);
      lastLogTime = millis();
    }
  }
}
