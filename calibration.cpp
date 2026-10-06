#include <Arduino.h>
#include <FS.h>
#include <SD_MMC.h>
#include <math.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ============================================================
// USER CONFIGURATION & PIN DEFINITIONS
// ============================================================
const bool USE_PH_PROBE   = true;
const bool USE_DO_PROBE   = true;
const bool USE_OD_PROBE   = true;

#define PIN_BUTTON 19 // Updated to safe pin

#define PIN_OD_ADC      34
#define PIN_OD_LED      32
#define PIN_PH_ADC      35
#define PIN_DO_ADC      39 // VN Pin

#define PIN_OLED_SDA    21
#define PIN_OLED_SCL    22
#define SCREEN_WIDTH    128
#define SCREEN_HEIGHT   64
#define OLED_RESET      -1

#define PH_CAL_FILE "/ph_Calibration.txt"
#define DO_CAL_FILE "/do_Calibration.txt"
#define OD_CAL_FILE "/od_Calibration.txt"

float ph_slope = -5.70;
float ph_intercept = 21.34;
float do_slope = 100.0;
float do_intercept = 0.0;
float od_blank_net = 1.0;
const float MIN_SIGNAL = 0.0001;

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// ============================================================
// HELPER FUNCTIONS
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

void showMessage(String line1, String line2 = "", String line3 = "", String line4 = "") {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);   display.println(line1);
  display.setCursor(0, 16);  display.println(line2);
  display.setCursor(0, 32);  display.println(line3);
  display.setCursor(0, 48);  display.println(line4);
  display.display();
}

void waitForButtonPress() {
  while (digitalRead(PIN_BUTTON) == HIGH) delay(10);
  delay(50);
  while (digitalRead(PIN_BUTTON) == LOW) delay(10);
  delay(200);
}

// ============================================================
// FILE SAVING FUNCTIONS (UPDATED TO PREVENT TRUNCATION BUGS)
// ============================================================
void savePHCalibration() {
  if (SD_MMC.exists(PH_CAL_FILE)) {
    SD_MMC.remove(PH_CAL_FILE);
  }
  File file = SD_MMC.open(PH_CAL_FILE, FILE_WRITE);
  if (!file) return;
  file.println(String(ph_slope, 6));
  file.println(String(ph_intercept, 6));
  file.close();
}

void saveDOCalibration() {
  if (SD_MMC.exists(DO_CAL_FILE)) {
    SD_MMC.remove(DO_CAL_FILE);
  }
  File file = SD_MMC.open(DO_CAL_FILE, FILE_WRITE);
  if (!file) return;
  file.println(String(do_slope, 6));
  file.println(String(do_intercept, 6));
  file.close();
}

void saveODCalibration() {
  if (SD_MMC.exists(OD_CAL_FILE)) {
    SD_MMC.remove(OD_CAL_FILE);
  }
  File file = SD_MMC.open(OD_CAL_FILE, FILE_WRITE);
  if (!file) return;
  file.println(String(od_blank_net, 6));
  file.close();
}

// ============================================================
// CALIBRATION ROUTINES
// ============================================================
float captureVoltageOLED(int pin, String line1, String line2) {
  while (true) {
    float liveVoltage = readVoltage(pin, 20);
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);   display.println(line1);
    display.setCursor(0, 16);  display.println(line2);
    display.setCursor(0, 32);  display.print("Voltage: "); display.print(liveVoltage, 4); display.println(" V");
    display.setCursor(0, 48);  display.println("Press Button to save");
    display.display();

    if (digitalRead(PIN_BUTTON) == LOW) {
      delay(50);
      while (digitalRead(PIN_BUTTON) == LOW) delay(5);
      delay(200);
      showMessage("Captured:", String(liveVoltage, 4) + " V", "", "");
      delay(1000);
      return liveVoltage;
    }
    delay(100);
  }
}

void calibratePHForcedOLED() {
  if (!USE_PH_PROBE) return;
  showMessage("pH Calibration", "Starting...", "", "");
  delay(1000);

  float v7 = captureVoltageOLED(PIN_PH_ADC, "Place pH probe", "in pH 7 buffer");
  float v4 = captureVoltageOLED(PIN_PH_ADC, "Place pH probe", "in pH 4 buffer");
  float v10 = captureVoltageOLED(PIN_PH_ADC, "Place pH probe", "in pH 10 buffer");

  float targetPH[3] = {7.0, 4.0, 10.0};
  float voltage[3] = {v7, v4, v10};
  float sumV = 0, sumPH = 0, sumVV = 0, sumVPH = 0;

  for (int i = 0; i < 3; i++) {
    sumV += voltage[i]; sumPH += targetPH[i];
    sumVV += voltage[i] * voltage[i]; sumVPH += voltage[i] * targetPH[i];
  }

  float n = 3.0;
  float denominator = n * sumVV - sumV * sumV;

  if (fabs(denominator) < 0.0001) {
    showMessage("pH Cal Failed", "Math Error", "", "");
    delay(1500);
    return;
  }

  ph_slope = (n * sumVPH - sumV * sumPH) / denominator;
  ph_intercept = (sumPH - ph_slope * sumV) / n;
  savePHCalibration();

  showMessage("pH Cal Saved", "Slope:" + String(ph_slope, 2), "Int:" + String(ph_intercept, 2), "");
  delay(2000);
}

void calibrateDOForcedOLED() {
  if (!USE_DO_PROBE) return;
  showMessage("DO Calibration", "Starting...", "", "");
  delay(1000);

  // 1. Capture 100% saturation voltage
  float v100 = captureVoltageOLED(PIN_DO_ADC, "Place DO probe", "in 100% sat water");
  
  // 2. Capture 0% saturation voltage
  float v0 = captureVoltageOLED(PIN_DO_ADC, "Place DO probe", "in 0% sat solution");

  // 3. Prevent division by zero if voltages are too similar
  if (fabs(v100 - v0) < 0.0001) {
    showMessage("DO Cal Failed", "Identical Voltages", "Check Probe/Buffer", "");
    delay(2000);
    return;
  }

  // 4. Calculate new slope and intercept
  do_slope = 100.0 / (v100 - v0);
  do_intercept = -(do_slope * v0);
  
  // 5. Save and confirm
  saveDOCalibration();
  showMessage("DO Cal Saved", "Slope: " + String(do_slope, 2), "Int: " + String(do_intercept, 2), "");
  delay(2000);
}

void calibrateODForcedOLED() {
  if (!USE_OD_PROBE) return;
  showMessage("OD Calibration", "Place blank media", "Press Button", "when ready");
  waitForButtonPress();
  showMessage("Capturing OD", "blank...", "", "");

  digitalWrite(PIN_OD_LED, LOW);
  delay(500);
  float darkV = readVoltage(PIN_OD_ADC, 100);

  digitalWrite(PIN_OD_LED, HIGH);
  delay(500);
  float lightV = readVoltage(PIN_OD_ADC, 100);
  digitalWrite(PIN_OD_LED, LOW);

  od_blank_net = lightV - darkV;
  if (od_blank_net < MIN_SIGNAL) od_blank_net = MIN_SIGNAL;
  
  saveODCalibration();
  showMessage("OD Cal Saved", "Blank net:", String(od_blank_net, 4) + " V", "");
  delay(2000);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_OD_LED, OUTPUT);
  digitalWrite(PIN_OD_LED, LOW);

  setupOLED();

  if (!SD_MMC.begin("/sdcard", true)) {
    showMessage("SD Card Error!", "Cannot save cal.", "Insert & Reset", "");
    while (true) delay(100);
  }

  showMessage("Calibration Mode", "Starting in 3s...", "", "");
  delay(3000);

  calibratePHForcedOLED();
  calibrateDOForcedOLED();
  calibrateODForcedOLED();

  showMessage("Calibration", "Complete!", "Values saved to SD.", "Ready to load Run code");
}

void loop() {
  // Calibration completes in setup.
}
