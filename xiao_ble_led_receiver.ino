#include <ArduinoBLE.h>

// XIAO nRF52840 Sense の内蔵LED
const int LED_PIN = LED_BUILTIN;

// BLEの名前
const char* DEVICE_NAME = "PoseRing_YELLOW";

// UUIDはPC側Pythonと一致させる必要があります
BLEService poseRingService("19B10000-E8F2-537E-4F6C-D104768A1214");
BLEByteCharacteristic ledCharacteristic(
  "19B10001-E8F2-537E-4F6C-D104768A1214",
  BLERead | BLEWrite
);

void setup() {
  pinMode(LED_PIN, OUTPUT);

  // XIAO nRF52840 Sense は LOWで点灯、HIGHで消灯
  digitalWrite(LED_PIN, HIGH);

  if (!BLE.begin()) {
    // BLE開始失敗時は何もしない
    while (1);
  }

  BLE.setLocalName(DEVICE_NAME);
  BLE.setDeviceName(DEVICE_NAME);
  BLE.setAdvertisedService(poseRingService);

  poseRingService.addCharacteristic(ledCharacteristic);
  BLE.addService(poseRingService);

  // 初期値 0 = OFF
  ledCharacteristic.writeValue((byte)0);

  BLE.advertise();
}

void loop() {
  BLEDevice central = BLE.central();

  if (central) {
    while (central.connected()) {
      if (ledCharacteristic.written()) {
        byte value = ledCharacteristic.value();

        if (value == 1 || value == '1') {
          digitalWrite(LED_PIN, LOW);   // 点灯
        } else if (value == 0 || value == '0') {
          digitalWrite(LED_PIN, HIGH);  // 消灯
        }
      }
    }

    // 切断されたら安全のため消灯
    digitalWrite(LED_PIN, HIGH);
  }
}
