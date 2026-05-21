// Bep-Project firmware voor Arduino Nano
// Hardware: 3x 28BYJ-48 + ULN2003 + WS2812B-8 (NeoPixel)
//
// Ontvangt ASCII-commando's over USB-serial @ 9600 baud:
//   "1 500\n"          -> motor 1 naar absolute positie 500 stappen
//   "2 -250\n"         -> motor 2 naar -250
//   "3 1000\n"         -> motor 3 naar 1000
//   "SPEED 600\n"      -> max snelheid voor alle motoren (stappen/s)
//   "STOP\n"           -> noodstop, alle motoren onmiddellijk stil
//   "LAMP 128\n"       -> WS2812B-helderheid lamp BINNEN 0..255 (alle 8 pixels wit)
//   "LAMP2 128\n"      -> WS2812B-helderheid lamp BUITEN 0..255 (alle 8 pixels wit)
//   "SETPOS 1 0\n"     -> zet motor 1 op positie 0 zonder te bewegen (soft-home)
//   "WHERE\n"          -> antwoord: "POS <m1> <m2> <m3>"  (huidige posities)
//   "BUSY?\n"          -> antwoord: "BUSY 1" (rijdt) of "BUSY 0" (stilstand)
//   "GOTO 100 -50 0\n" -> alle 3 motoren tegelijk naar absolute target
//
// Hardware-aannames:
//   - 3x ULN2003 driverbord met 28BYJ-48 motor:
//       Motor 1 ULN2003: IN1=D2, IN2=D3, IN3=D4, IN4=D5
//       Motor 2 ULN2003: IN1=D6, IN2=D7, IN3=D8, IN4=D9
//       Motor 3 ULN2003: IN1=D10, IN2=D11, IN3=D12, IN4=D13  (D13 = onboard LED, flickert mee)
//     ULN2003-boards: VCC = aparte 5V voeding, GND = gemeenschappelijk met Arduino GND
//   - WS2812B-8 ring BINNEN: DIN op A2 (= digital pin 16), via 470 ohm
//   - WS2812B-8 ring BUITEN: DIN op A3 (= digital pin 17), via 470 ohm
//
// AccelStepper FULL4WIRE pin-volgorde-truc:
//   28BYJ-48 + ULN2003 wordt fysiek bedraad als IN1-IN2-IN3-IN4,
//   maar het step-sequence patroon is IN1-IN3-IN2-IN4.
//   Daarom swappen we pin 2 en pin 3 in de constructor.
//
// Library: Adafruit NeoPixel + AccelStepper (beide via Library Manager)

#include <AccelStepper.h>
#include <Adafruit_NeoPixel.h>

// ---- Motor pin-config (FULL4WIRE, volgorde IN1, IN3, IN2, IN4) -
AccelStepper m1(AccelStepper::FULL4WIRE, 2,  4,  3,  5);
AccelStepper m2(AccelStepper::FULL4WIRE, 6,  8,  7,  9);
AccelStepper m3(AccelStepper::FULL4WIRE, 10, 12, 11, 13);

// ---- Lamp config -----------------------------------------------
const uint8_t LAMP_PIN    = 16;   // A2 = D16 op de Nano (lamp BINNEN)
const uint8_t LAMP2_PIN   = 17;   // A3 = D17 op de Nano (lamp BUITEN)
const uint8_t LAMP_COUNT  = 8;

Adafruit_NeoPixel lamp (LAMP_COUNT, LAMP_PIN,  NEO_GRB + NEO_KHZ800);  // binnen
Adafruit_NeoPixel lampB(LAMP_COUNT, LAMP2_PIN, NEO_GRB + NEO_KHZ800);  // buiten

// ---- Globals ---------------------------------------------------
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

void setLampB(uint8_t brightness) {
  lampB.setBrightness(brightness);
  for (uint8_t i = 0; i < LAMP_COUNT; i++) {
    lampB.setPixelColor(i, lampB.Color(255, 255, 255));
  }
  lampB.show();
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
  if (line.startsWith("LAMP2 ")) {
    int b = line.substring(6).toInt();
    b = constrain(b, 0, 255);
    setLampB((uint8_t)b);
    Serial.print("OK LAMP2 "); Serial.println(b);
    return;
  }
  if (line.startsWith("LAMP ")) {
    int b = line.substring(5).toInt();
    b = constrain(b, 0, 255);
    setLamp((uint8_t)b);
    Serial.print("OK LAMP "); Serial.println(b);
    return;
  }
  if (line == "WHERE") {
    Serial.print("POS ");
    Serial.print(m1.currentPosition()); Serial.print(' ');
    Serial.print(m2.currentPosition()); Serial.print(' ');
    Serial.println(m3.currentPosition());
    return;
  }
  if (line == "BUSY?") {
    bool busy = (m1.distanceToGo() != 0)
             || (m2.distanceToGo() != 0)
             || (m3.distanceToGo() != 0);
    Serial.print("BUSY "); Serial.println(busy ? 1 : 0);
    return;
  }
  if (line.startsWith("GOTO ")) {
    // GOTO <m1> <m2> <m3>
    int sp1 = line.indexOf(' ', 5);
    if (sp1 <= 0) return;
    int sp2 = line.indexOf(' ', sp1 + 1);
    if (sp2 <= 0) return;
    long t1 = line.substring(5, sp1).toInt();
    long t2 = line.substring(sp1 + 1, sp2).toInt();
    long t3 = line.substring(sp2 + 1).toInt();
    m1.moveTo(t1);
    m2.moveTo(t2);
    m3.moveTo(t3);
    Serial.print("OK GOTO "); Serial.print(t1);
    Serial.print(' '); Serial.print(t2);
    Serial.print(' '); Serial.println(t3);
    return;
  }
  if (line.startsWith("SETPOS ")) {
    // SETPOS <motor> <position>
    int sp = line.indexOf(' ', 7);
    if (sp <= 0) return;
    int motor = line.substring(7, sp).toInt();
    long pos = line.substring(sp + 1).toInt();
    AccelStepper* m = nullptr;
    switch (motor) {
      case 1: m = &m1; break;
      case 2: m = &m2; break;
      case 3: m = &m3; break;
      default: return;
    }
    m->setCurrentPosition(pos);
    Serial.print("OK SETPOS "); Serial.print(motor);
    Serial.print(' '); Serial.println(pos);
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

  applySpeed(currentMaxSpeed);

  lamp.begin();
  lamp.setBrightness(0);
  lamp.show();

  lampB.begin();
  lampB.setBrightness(0);
  lampB.show();

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
