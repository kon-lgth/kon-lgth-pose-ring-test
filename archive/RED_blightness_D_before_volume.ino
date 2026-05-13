#include <ArduinoBLE.h>
#include <DFRobotDFPlayerMini.h>
#include <Adafruit_NeoPixel.h>

// ============================================================
// PoseRing device firmware
// - BLE接続中は白色に点灯
// - ゴール外では距離に応じて白→赤へ変化
// - ゴール判定内に入っている間は赤点滅
// - ゴール判定内に3秒間入り続けたら音が鳴る
// - ゴール外に出たら3秒カウントをリセット
// - 切断時・終了時は消灯
//
// PC側から受け取る値:
//   0      = OFF
//   1      = BLE接続中 / 待機表示 = 白
//   2〜255 = 赤LEDの強さ
//   250〜255程度 = ゴール判定内として扱う
// ============================================================

// NeoPixel設定
#define NUM_LEDS 48
#define DATA_PIN 4
#define LED_BRIGHTNESS 50

// 白色の明るさ
#define WHITE_R 80
#define WHITE_G 80
#define WHITE_B 80

// ゴール判定・点滅・音
#define GOAL_BRIGHTNESS_THRESHOLD 250
#define GOAL_SOUND_DELAY_MS 3000
#define BLINK_INTERVAL_MS 200

Adafruit_NeoPixel strip(NUM_LEDS, DATA_PIN, NEO_GRB + NEO_KHZ800);

// DFPlayer設定
DFRobotDFPlayerMini myDFPlayer;
bool dfPlayerReady = false;

// BLE設定：PC側Pythonと一致させる
const char* DEVICE_NAME = "PoseRing_YELLOW";

BLEService poseRingService("19B10000-E8F2-537E-4F6C-D104768A1214");

BLEByteCharacteristic feedbackCharacteristic(
  "19B10001-E8F2-537E-4F6C-D104768A1214",
  BLERead | BLEWrite
);

// 状態定義
const byte STATE_OFF = 0;
const byte STATE_CONNECTED_WHITE = 1;
const byte STATE_RED_MIN_BRIGHTNESS = 2;

byte currentState = STATE_OFF;
byte previousState = 255;

// ゴール状態管理
bool inGoal = false;
bool goalSoundPlayed = false;
bool blinkOn = false;

unsigned long goalStartTime = 0;
unsigned long lastBlinkTime = 0;

// ------------------------------------------------------------
// LED全体を指定色にする
// ------------------------------------------------------------
void setAllPixels(uint8_t r, uint8_t g, uint8_t b) {
  for (int i = 0; i < NUM_LEDS; i++) {
    strip.setPixelColor(i, strip.Color(r, g, b));
  }
  strip.show();
}

// ------------------------------------------------------------
// 受け取った値に応じて白→赤へ変化させる
// value: 2〜255
// ------------------------------------------------------------
void setRedByBrightness(byte brightnessValue) {
  float t = (brightnessValue - 2) / 253.0;
  t = constrain(t, 0.0, 1.0);

  int r = WHITE_R + (255 - WHITE_R) * t;
  int g = WHITE_G * (1.0 - t);
  int b = WHITE_B * (1.0 - t);

  setAllPixels(r, g, b);
}

// ------------------------------------------------------------
// 状態をLEDに反映
// ------------------------------------------------------------
void applyState(byte state) {
  if (state == STATE_OFF) {
    inGoal = false;
    goalSoundPlayed = false;
    setAllPixels(0, 0, 0);
    previousState = state;
    Serial.println("LED OFF");
    return;
  }

  if (state == STATE_CONNECTED_WHITE) {
    inGoal = false;
    goalSoundPlayed = false;
    setAllPixels(WHITE_R, WHITE_G, WHITE_B);
    previousState = state;
    Serial.println("BLE CONNECTED: WHITE");
    return;
  }

  if (state >= STATE_RED_MIN_BRIGHTNESS) {
    if (state >= GOAL_BRIGHTNESS_THRESHOLD) {
      if (!inGoal) {
        inGoal = true;
        goalSoundPlayed = false;
        blinkOn = true;
        goalStartTime = millis();
        lastBlinkTime = millis();

        setAllPixels(255, 0, 0);
        Serial.println("GOAL ENTER: BLINK START");
      }
    } else {
      if (inGoal) {
        Serial.println("GOAL EXIT: TIMER RESET");
      }

      inGoal = false;
      goalSoundPlayed = false;
      setRedByBrightness(state);
    }

    previousState = state;
  }
}

// ------------------------------------------------------------
// ゴール中の点滅と3秒後の音
// ------------------------------------------------------------
void updateGoalFeedback() {
  if (!inGoal) {
    return;
  }

  unsigned long now = millis();

  // ゴール内にいる間はずっと赤点滅
  if (now - lastBlinkTime >= BLINK_INTERVAL_MS) {
    lastBlinkTime = now;
    blinkOn = !blinkOn;

    if (blinkOn) {
      setAllPixels(255, 0, 0);
    } else {
      setAllPixels(0, 0, 0);
    }
  }

  // ゴール内に3秒間入り続けたら音を鳴らす
  if (!goalSoundPlayed && now - goalStartTime >= GOAL_SOUND_DELAY_MS) {
    goalSoundPlayed = true;

    if (dfPlayerReady) {
      myDFPlayer.play(1);
      Serial.println("GOAL KEEP 3 SEC: SOUND PLAY");
    }
  }
}

// ------------------------------------------------------------
// BLEで受け取った値を状態に変換
// ------------------------------------------------------------
byte normalizeReceivedValue(byte value) {
  if (value == 0 || value == '0') {
    return STATE_OFF;
  }

  if (value == 1 || value == '1') {
    return STATE_CONNECTED_WHITE;
  }

  // Python側から bytes([brightness]) で送る場合、
  // 2〜255 は赤の明るさとして扱う
  if (value >= 2) {
    return value;
  }

  return STATE_CONNECTED_WHITE;
}

void setup() {
  Serial.begin(115200);

  // NeoPixel初期化
  strip.begin();
  strip.setBrightness(LED_BRIGHTNESS);
  setAllPixels(0, 0, 0);

  // DFPlayer初期化
  // XIAO nRF52840 SenseのSerial1: D6=TX, D7=RX想定
  Serial1.begin(9600);
  delay(1000);

  if (myDFPlayer.begin(Serial1)) {
    dfPlayerReady = true;
    myDFPlayer.volume(10); // 0〜30
    Serial.println("DFPlayer ready");
  } else {
    Serial.println("DFPlayer init failed");
  }

  // BLE初期化
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

  Serial.println("PoseRing BLE red brightness blink device ready");
}

void loop() {
  BLEDevice central = BLE.central();

  if (central) {
    Serial.print("Connected: ");
    Serial.println(central.address());

    // BLE接続が成立した時点で白色に点灯
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

    // 切断時は安全のため消灯
    currentState = STATE_OFF;
    applyState(currentState);

    previousState = 255;

    Serial.println("Disconnected");
  }
}