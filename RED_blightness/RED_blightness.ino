#include <ArduinoBLE.h>
#include <DFRobotDFPlayerMini.h>
#include <Adafruit_NeoPixel.h>

// ============================================================
// PoseRing device firmware
// - BLE接続中は白色に点灯
// - 黄色がゴール判定に入ったら黄色に点灯
// - 切断時・終了時は消灯
//
// PC側から受け取る値:
//   0 = OFF
//   1 = BLE接続中 / 待機表示 = 白
//   2 = 黄色ゴール判定中 = 黄色
// 文字 '0'/'1'/'2' にも対応
// ============================================================

// NeoPixel設定
#define NUM_LEDS 48
#define DATA_PIN 4
#define LED_BRIGHTNESS 20

// 色の明るさ。眩しい場合は値を下げる
#define WHITE_R 80
#define WHITE_G 80
#define WHITE_B 80

#define YELLOW_R 255
#define YELLOW_G 0
#define YELLOW_B 0

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

const byte STATE_OFF = 0;
const byte STATE_CONNECTED_WHITE = 1;
const byte STATE_YELLOW_GOAL = 2;

byte currentState = STATE_OFF;
byte previousState = 255;

void setAllPixels(uint8_t r, uint8_t g, uint8_t b) {
  for (int i = 0; i < NUM_LEDS; i++) {
    strip.setPixelColor(i, strip.Color(r, g, b));
  }
  strip.show();
}

void applyState(byte state) {
  if (state == previousState) {
    return;
  }

  if (state == STATE_OFF) {
    setAllPixels(0, 0, 0);
    Serial.println("LED OFF");
  } else if (state == STATE_CONNECTED_WHITE) {
    setAllPixels(WHITE_R, WHITE_G, WHITE_B);
    Serial.println("BLE CONNECTED: WHITE");
  } else if (state == STATE_YELLOW_GOAL) {
    setAllPixels(YELLOW_R, YELLOW_G, YELLOW_B);
    Serial.println("YELLOW GOAL: YELLOW");

    // 黄色ゴールに入った瞬間だけ効果音を鳴らす
    // microSD内の /mp3/0001.mp3 または 0001.mp3 を想定
    if (dfPlayerReady) {
      myDFPlayer.play(1);
    }
  }

  previousState = state;
}

byte normalizeReceivedValue(byte value) {
  if (value == 0 || value == '0') return STATE_OFF;
  if (value == 1 || value == '1') return STATE_CONNECTED_WHITE;
  if (value == 2 || value == '2') return STATE_YELLOW_GOAL;

  // 想定外の値は安全側で白に戻す
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
    myDFPlayer.volume(10); // 0-30
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

  Serial.println("PoseRing BLE white/yellow device ready");
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
    }

    // 切断時は安全のため消灯
    currentState = STATE_OFF;
    applyState(currentState);
    previousState = 255;
    Serial.println("Disconnected");
  }
}
