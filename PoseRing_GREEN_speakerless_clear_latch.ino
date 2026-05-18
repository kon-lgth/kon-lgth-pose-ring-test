#include <ArduinoBLE.h>
#include <Adafruit_NeoPixel.h>

// ============================================================
// PoseRing GREEN device firmware / speakerless
// - BLE接続中は白色に点灯
// - ゴール外では距離に応じて白→赤へ変化
// - ゴール判定内に入っている間はgreen blink
// - スピーカーなし。音は赤マイコンだけが担当する
// - 251を受け取っても何もしない。252で自分の色を最大点灯
// - 切断時・終了時は消灯
// ============================================================

#define NUM_LEDS 48
#define DATA_PIN 4
#define LED_BRIGHTNESS 50

#define WHITE_R 80
#define WHITE_G 80
#define WHITE_B 80

// このリング自身の最大色
#define RING_R 0
#define RING_G 255
#define RING_B 0

#define GOAL_BRIGHTNESS_THRESHOLD 250
#define CLEAR_SOUND_COMMAND 251
#define CLEAR_SOLID_MAX_COMMAND 252
#define BLINK_INTERVAL_MS 200

Adafruit_NeoPixel strip(NUM_LEDS, DATA_PIN, NEO_GRB + NEO_KHZ800);

const char* DEVICE_NAME = "PoseRing_GREEN";

BLEService poseRingService("19B10000-E8F2-537E-4F6C-D104768A1214");
BLEByteCharacteristic feedbackCharacteristic(
  "19B10001-E8F2-537E-4F6C-D104768A1214",
  BLERead | BLEWrite
);

const byte STATE_OFF = 0;
const byte STATE_CONNECTED_WHITE = 1;
const byte STATE_COLOR_MIN_BRIGHTNESS = 2;

byte currentState = STATE_OFF;
bool inGoal = false;
bool blinkOn = false;
unsigned long lastBlinkTime = 0;

void setAllPixels(uint8_t r, uint8_t g, uint8_t b) {
  for (int i = 0; i < NUM_LEDS; i++) {
    strip.setPixelColor(i, strip.Color(r, g, b));
  }
  strip.show();
}

void setColorByBrightness(byte brightnessValue) {
  float t = (brightnessValue - 2) / 253.0;
  t = constrain(t, 0.0, 1.0);

  int r = WHITE_R + (RING_R - WHITE_R) * t;
  int g = WHITE_G + (RING_G - WHITE_G) * t;
  int b = WHITE_B + (RING_B - WHITE_B) * t;

  setAllPixels(r, g, b);
}

void applyState(byte state) {
  if (state == STATE_OFF) {
    inGoal = false;
    setAllPixels(0, 0, 0);
    Serial.println("LED OFF");
    return;
  }

  if (state == STATE_CONNECTED_WHITE) {
    inGoal = false;
    setAllPixels(WHITE_R, WHITE_G, WHITE_B);
    Serial.println("BLE CONNECTED: WHITE");
    return;
  }

  if (state == CLEAR_SOUND_COMMAND) {
    // 音は赤だけ。スピーカーなしリングでは何もしない。
    Serial.println("ALL CLEAR SOUND COMMAND IGNORED");
    return;
  }

  if (state == CLEAR_SOLID_MAX_COMMAND) {
    // ALL CLEAR直後の2秒間、リング自身の色で最大点灯を維持する。
    inGoal = false;
    setAllPixels(RING_R, RING_G, RING_B);
    Serial.println("ALL CLEAR: SOLID COLOR MAX");
    return;
  }

  if (state >= STATE_COLOR_MIN_BRIGHTNESS) {
    if (state >= GOAL_BRIGHTNESS_THRESHOLD) {
      if (!inGoal) {
        inGoal = true;
        blinkOn = true;
        lastBlinkTime = millis();
        setAllPixels(RING_R, RING_G, RING_B);
        Serial.println("GOAL ENTER: BLINK START");
      }
    } else {
      if (inGoal) {
        Serial.println("GOAL EXIT");
      }
      inGoal = false;
      setColorByBrightness(state);
    }
  }
}

void updateGoalFeedback() {
  if (!inGoal) return;

  unsigned long now = millis();
  if (now - lastBlinkTime >= BLINK_INTERVAL_MS) {
    lastBlinkTime = now;
    blinkOn = !blinkOn;
    if (blinkOn) {
      setAllPixels(RING_R, RING_G, RING_B);
    } else {
      setAllPixels(0, 0, 0);
    }
  }
}

byte normalizeReceivedValue(byte value) {
  if (value == 0 || value == '0') return STATE_OFF;
  if (value == 1 || value == '1') return STATE_CONNECTED_WHITE;
  if (value >= 2) return value;
  return STATE_CONNECTED_WHITE;
}

void setup() {
  Serial.begin(115200);

  strip.begin();
  strip.setBrightness(LED_BRIGHTNESS);
  setAllPixels(0, 0, 0);

  if (!BLE.begin()) {
    Serial.println("BLE init failed");
    while (1);
  }

  BLE.setLocalName(DEVICE_NAME);
  BLE.setDeviceName(DEVICE_NAME);
  BLE.setAdvertisedService(poseRingService);

  poseRingService.addCharacteristic(feedbackCharacteristic);
  BLE.addService(poseRingService);

  feedbackCharacteristic.writeValue(STATE_OFF);
  BLE.advertise();

  Serial.print("PoseRing GREEN speakerless BLE device ready: ");
  Serial.println(DEVICE_NAME);
}

void loop() {
  BLEDevice central = BLE.central();

  if (central) {
    Serial.print("Connected: ");
    Serial.println(central.address());

    currentState = STATE_CONNECTED_WHITE;
    applyState(currentState);

    while (central.connected()) {
      if (feedbackCharacteristic.written()) {
        byte value = feedbackCharacteristic.value();
        currentState = normalizeReceivedValue(value);
        applyState(currentState);
      }
      updateGoalFeedback();
    }

    currentState = STATE_OFF;
    applyState(currentState);
    Serial.println("Disconnected");
  }
}
