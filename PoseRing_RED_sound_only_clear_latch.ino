#include <ArduinoBLE.h>
#include <DFRobotDFPlayerMini.h>
#include <Adafruit_NeoPixel.h>

// ============================================================
// PoseRing RED device firmware
// - BLE接続中は白色に点灯
// - ゴール外では距離に応じて白→赤へ変化
// - ゴール判定内に入っている間は赤点滅
// - 4色ALL CLEAR時だけ、PC側から 251 を受け取って赤マイコンだけ音を鳴らす
// - 252を受け取ると赤最大で点灯し、ALL CLEAR後2秒間の見た目を維持する
// - 切断時・終了時は消灯
//
// PC側から受け取る値:
//   0      = OFF
//   1      = BLE接続中 / 待機表示 = 白
//   2〜249 = 赤LEDの強さ
//   250    = ゴール判定内として扱う（赤点滅）
//   251    = 4色ALL CLEAR効果音を鳴らす（赤のみ）
//   252    = ALL CLEAR後、赤最大点灯を維持
// ============================================================

// NeoPixel設定
#define NUM_LEDS 48
#define DATA_PIN 4
#define LED_BRIGHTNESS 50

// 白色の明るさ
#define WHITE_R 80
#define WHITE_G 80
#define WHITE_B 80

// このリング自身の最大色
#define RING_R 255
#define RING_G 0
#define RING_B 0

// ゴール判定・点滅・音
#define GOAL_BRIGHTNESS_THRESHOLD 250
#define CLEAR_SOUND_COMMAND 251
#define CLEAR_SOLID_MAX_COMMAND 252
#define BLINK_INTERVAL_MS 200

Adafruit_NeoPixel strip(NUM_LEDS, DATA_PIN, NEO_GRB + NEO_KHZ800);

// DFPlayer設定
DFRobotDFPlayerMini myDFPlayer;
bool dfPlayerReady = false;

// 爆音対策用のDFPlayer音量設定（0〜30）
#define DFPLAYER_SAFE_VOLUME 10
#define DFPLAYER_VOLUME_SETTLE_MS 80

// BLE設定：PC側Pythonと一致させる
const char* DEVICE_NAME = "PoseRing_RED";

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
bool blinkOn = false;
unsigned long lastBlinkTime = 0;

void setAllPixels(uint8_t r, uint8_t g, uint8_t b) {
  for (int i = 0; i < NUM_LEDS; i++) {
    strip.setPixelColor(i, strip.Color(r, g, b));
  }
  strip.show();
}

void setRedByBrightness(byte brightnessValue) {
  float t = (brightnessValue - 2) / 253.0;
  t = constrain(t, 0.0, 1.0);

  int r = WHITE_R + (255 - WHITE_R) * t;
  int g = WHITE_G * (1.0 - t);
  int b = WHITE_B * (1.0 - t);

  setAllPixels(r, g, b);
}

void playClearSound() {
  if (dfPlayerReady) {
    // 爆音対策：再生直前に毎回、安全音量を再設定する。
    myDFPlayer.volume(DFPLAYER_SAFE_VOLUME);
    delay(DFPLAYER_VOLUME_SETTLE_MS);
    myDFPlayer.play(1);
    Serial.println("ALL CLEAR: SOUND PLAY");
  } else {
    Serial.println("DFPlayer not ready: sound skipped");
  }
}

void applyState(byte state) {
  if (state == STATE_OFF) {
    inGoal = false;
    setAllPixels(0, 0, 0);
    previousState = state;
    Serial.println("LED OFF");
    return;
  }

  if (state == STATE_CONNECTED_WHITE) {
    inGoal = false;
    setAllPixels(WHITE_R, WHITE_G, WHITE_B);
    previousState = state;
    Serial.println("BLE CONNECTED: WHITE");
    return;
  }

  if (state == CLEAR_SOUND_COMMAND) {
    // 赤だけクリア音を鳴らす。LEDは赤最大点灯にして、直後のクリア演出につなげる。
    inGoal = false;
    setAllPixels(RING_R, RING_G, RING_B);
    playClearSound();
    previousState = state;
    Serial.println("ALL CLEAR SOUND COMMAND / RED SOLID MAX");
    return;
  }

  if (state == CLEAR_SOLID_MAX_COMMAND) {
    // ALL CLEAR直後の2秒間、赤最大点灯を維持する。
    inGoal = false;
    setAllPixels(RING_R, RING_G, RING_B);
    previousState = state;
    Serial.println("ALL CLEAR: RED SOLID MAX");
    return;
  }

  if (state >= STATE_RED_MIN_BRIGHTNESS) {
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
      setRedByBrightness(state);
    }
    previousState = state;
  }
}

void updateGoalFeedback() {
  if (!inGoal) {
    return;
  }

  unsigned long now = millis();

  // ゴール内にいる間は赤点滅。音はここでは鳴らさない。
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
  if (value == 0 || value == '0') {
    return STATE_OFF;
  }
  if (value == 1 || value == '1') {
    return STATE_CONNECTED_WHITE;
  }
  if (value >= 2) {
    return value;
  }
  return STATE_CONNECTED_WHITE;
}

void setup() {
  Serial.begin(115200);

  strip.begin();
  strip.setBrightness(LED_BRIGHTNESS);
  setAllPixels(0, 0, 0);

  // DFPlayer初期化
  // XIAO nRF52840 SenseのSerial1: D6=TX, D7=RX想定
  Serial1.begin(9600);
  delay(1000);

  if (myDFPlayer.begin(Serial1)) {
    dfPlayerReady = true;
    myDFPlayer.volume(DFPLAYER_SAFE_VOLUME);
    Serial.println("DFPlayer ready");
  } else {
    Serial.println("DFPlayer init failed");
  }

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

  Serial.println("PoseRing RED BLE sound-only-clear device ready");
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
    previousState = 255;

    Serial.println("Disconnected");
  }
}
