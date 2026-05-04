// Bep-Project firmware voor Arduino Nano
//
// Ontvangt ASCII-commando's over USB-serial @ 9600 baud:
//   "1 500\n"      -> motor 1 naar absolute positie 500 stappen
//   "2 -250\n"     -> motor 2 naar -250
//   "3 1000\n"     -> motor 3 naar 1000
//   "SPEED 800\n"  -> max snelheid voor alle motoren (stappen/s)
//   "STOP\n"       -> noodstop, alle motoren onmiddellijk stil
//   "LAMP 128\n"   -> WS2812B-helderheid 0..255 (alle 8 pixels wit)
//
// Hardware-aannames (PAS AAN INDIEN ANDERS):
//   - Drie A4988/DRV8825 drivers op CNC-shield V3 layout:
//       Motor 1: STEP=D2, DIR=D5
//       Motor 2: STEP=D3, DIR=D6
//       Motor 3: STEP=D4, DIR=D7
//       ENABLE (alle drivers): D8 (active LOW)
//   - WS2812B-8 ring: DIN op A2 (= digital pin 16), via 470 ohm
//
// Library: Adafruit NeoPixel + AccelStepper (beide via Library Manager)

#include <AccelStepper.h>
#include <Adafruit_NeoPixel.h>

// ---- Motor pin-config (verifieer dit met je bedrading) ---------
const uint8_t M1_STEP = 2, M1_DIR = 5;
const uint8_t M2_STEP = 3, M2_DIR = 6;
const uint8_t M3_STEP = 4, M3_DIR = 7;
const uint8_t MOTOR_ENABLE = 8;   // active LOW

// ---- Lamp config -----------------------------------------------
const uint8_t LAMP_PIN   = 16;    // A2 = D16 op de Nano
const uint8_t LAMP_COUNT = 8;

// ---- Globals ---------------------------------------------------
AccelStepper m1(AccelStepper::DRIVER, M1_STEP, M1_DIR);
AccelStepper m2(AccelStepper::DRIVER, M2_STEP, M2_DIR);
AccelStepper m3(AccelStepper::DRIVER, M3_STEP, M3_DIR);

Adafruit_NeoPixel lamp(LAMP_COUNT, LAMP_PIN, NEO_GRB + NEO_KHZ800);

float currentMaxSpeed = 500.0f;
String inbuf;

void applySpeed(float v) {
  currentMaxSpeed = v;
  m1.setMaxSpeed(v); m1.setAcceleration(v * 4);
  m2.setMaxSpeed(v); m2.setAcceleration(v * 4);
  m3.setMaxSpeed(v); m3.setAcceleration(v * 4);
}

void emergencyStop() {
  m1.stop(); m2.stop(); m3.stop();
  m1.setCurrentPosition(m1.currentPosition());
  m2.setCurrentPosition(m2.currentPosition());
  m3.setCurrentPosition(m3.currentPosition());
}

void setLamp(uint8_t brightness) {
  lamp.setBrightness(brightness);
  for (uint8_t i = 0; i < LAMP_COUNT; i++) {
    lamp.setPixelColor(i, lamp.Color(255, 255, 255));
  }
  lamp.show();
}

void handleCommand(const String& line) {
  if (line.length() == 0) return;

  if (line == "STOP") {
    emergencyStop();
    Serial.println("OK STOP");
    return;
  }
  if (line.startsWith("SPEED ")) {
    float v = line.substring(6).toFloat();
    if (v > 0) {
      applySpeed(v);
      Serial.print("OK SPEED "); Serial.println(v);
    }
    return;
  }
  if (line.startsWith("LAMP ")) {
    int b = line.substring(5).toInt();
    b = constrain(b, 0, 255);
    setLamp((uint8_t)b);
    Serial.print("OK LAMP "); Serial.println(b);
    return;
  }
  // Anders: "<motor> <target>"
  int sp = line.indexOf(' ');
  if (sp <= 0) return;
  int motor = line.substring(0, sp).toInt();
  long target = line.substring(sp + 1).toInt();
  switch (motor) {
    case 1: m1.moveTo(target); break;
    case 2: m2.moveTo(target); break;
    case 3: m3.moveTo(target); break;
    default: return;
  }
  Serial.print("OK "); Serial.print(motor);
  Serial.print(" "); Serial.println(target);
}

void setup() {
  Serial.begin(9600);

  pinMode(MOTOR_ENABLE, OUTPUT);
  digitalWrite(MOTOR_ENABLE, LOW);   // drivers aan

  applySpeed(currentMaxSpeed);

  lamp.begin();
  lamp.setBrightness(0);
  lamp.show();

  inbuf.reserve(32);
  Serial.println("READY");
}

void loop() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (inbuf.length() > 0) {
        handleCommand(inbuf);
        inbuf = "";
      }
    } else if (inbuf.length() < 64) {
      inbuf += c;
    }
  }
  m1.run();
  m2.run();
  m3.run();
}
