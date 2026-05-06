# PoseRingTest

## 概要 / Overview
2台のカメラを用いてステレオキャリブレーションを行い、  
マーカーの3次元位置を計測するプログラムです。

現在は、赤・黄・青・緑の4色マーカーの3D座標検出と、  
赤色マーカーのみを対象としたXIAO nRF52840 SenseへのLEDフィードバックの動作確認まで成功しています。  

This project performs stereo camera calibration using two cameras  
and computes the 3D positions of colored markers via triangulation.

Currently, the project supports 3D detection of red, yellow, blue, and green markers,  
and a BLE LED feedback test using XIAO nRF52840 Sense for the red marker.


---

## 必要環境 / Requirements
- Windows（動作確認済み / Verified）
- Python 3.10 +
- USB cameras × 2
- XIAO nRF52840 Sense（BLE LEDフィードバックを使う場合）
- NeoPixel LED Ring（リング用）
- DFPlayer Mini（リングのゴール音用）
---

## 必要ライブラリ / Required Libraries
以下をインストールしてください。
Install the following packages:

```bash
pip install opencv-python numpy
```

BLE通信を使う場合は、以下もインストールしてください。  
If you plan to use BLE communication, please install the following as well.
```bash
pip install bleak
```

## XIAO nRF52840 Sense 側のBLE LED受信プログラム

`redlight_ring.py` を使う場合、XIAO nRF52840 Senseには  
事前に `RED_blightness_D.ino` を書き込んでおく必要があります。  

このスケッチでは、XIAOを `PoseRing_YELLOW` という名前のBLEデバイスとして動作させます。  
BLE 受信値の意味  
  
0 = 消灯  
1 = BLE 接続中の白色表示  
2〜255 = 赤色 LED の輝度  
250〜255 = ゴール判定内（赤点滅＋3秒で音再生）   
XIAO nRF52840 Senseの内蔵LEDは `LOW` で点灯、`HIGH` で消灯します。   
  
    
When using redlight_ring.py, you must upload RED_blightness_D.ino to the XIAO nRF52840 Sense beforehand.  

In this sketch, the XIAO operates as a BLE device named PoseRing_YELLOW.  
The meanings of the BLE values received from the PC are as follows:  

0 = LED off  

1 = White LED indicating an active BLE connection  

2–255 = Red LED brightness  

250–255 = Treated as “inside the goal area” (red blinking + sound playback after 3 seconds)  

The built‑in LED on the XIAO nRF52840 Sense turns on with LOW and off with HIGH.  



## 実行手順 / How to Run
### ① キャリブレーション画像の取得 / Capture calibration image pairs
```bash
capture_calibration_pairs.py
```
→ calibration_images フォルダに画像が保存されます  
→ Calibration image pairs will be saved in the calibration_images folder.  
  
**capture_calibration_pairs.py は、以下の改善を含む版です。**  

・両カメラでチェッカーボードが検出できた場合のみ保存    
・ボードが動いている間は保存しない  
・一定時間静止したときのみ保存  
  
**The `capture_calibration_pairs.py` script has been updated to include the following improvements:** 

Save only when checkerboards are detected by both cameras  
Do not save while the board is moving  
Save only when the board has been stationary for a certain period of time  

  

### ② ステレオキャリブレーション / Stereo calibration
```bash
stereo_calibrate_from_saved_pairs.py
```
→ キャリブレーション結果（.npz ファイル）が生成されます  
→ A .npz calibration file will be generated.

### ③ 3D計測 / 3D measurement
```bash
four_color_3d_target_game.py
```
→ 各色の3次元座標が計算されます  
→ Computes the 3D coordinates of the each marker.  

**主な機能は以下です。**  

・赤、黄、青、緑の4色を同時に検出  
・ステレオキャリブレーション結果を用いて各色の3D座標を計算  
・Enterキーで現在の赤マーカー位置を原点に設定  
・sキーで現在の4色の3D座標を目標位置として保存  
・各色が目標位置から一定距離以内にあるかを判定  
・4色すべてが目標範囲内に一定時間入るとCLEAR表示  
・色を見失った場合は、最後に検出した3D座標を使用  
  
**The main features are as follows:**  

・Simultaneously detects four colors: red, yellow, blue, and green  
・Calculates the 3D coordinates for each color using stereo calibration results  
・Press the Enter key to set the current red marker position as the origin  
・Press the S key to save the current 3D coordinates of the four colors as the target position  
・Determines whether each color is within a certain distance from the target position  
・Displays “CLEAR” when all four colors remain within the target range for a certain period of time  
・If a color is lost, the last detected 3D coordinates are used  

### ④ 赤マーカー LEDリング＋音フィードバック / Red Marker LED Ring + Sound Feedback
```bash
redlight_ring.py
```
このプログラムでは、赤色マーカーを検出し、  
赤色が設定したゴール位置に入ったとき、PCからBLE通信でXIAO nRF52840 Senseへ信号を送り、  
リングLEDを点灯させます。
現在、この赤色のみのBluetooth版は動作確認済みです。  

**注意：XIAO側には、BLEデバイス名 PoseRing_YELLOW として動作するArduinoプログラムを書き込んでおく必要があります。**  
  
In this program, the red marker is detected, and when it enters the designated goal area,  
the PC sends a BLE signal to the XIAO nRF52840 Sense to activate the LED ring.  
This Bluetooth-based version for the red marker has been successfully verified.  
  
Note: You must upload an Arduino program to the XIAO so that it operates as a BLE device named PoseRing_YELLOW.    

  

## 事前に変更が必要な箇所 / Parameters to Modify
カメラインデックス / Camera indices

環境によってカメラ番号が異なるため、必要に応じて変更してください。  
Modify according to your environment.
```
CAM0_INDEX = 0
CAM1_INDEX = 1
```
セッションフォルダ / Session folder

キャリブレーションで保存されたフォルダを指定してください。  
Specify the folder where calibration images are stored.
```python
SESSION_DIR = "calibration_images/xxxx"
```
キャリブレーションファイル / Calibration file

生成された .npz ファイルのパスを指定してください。  
Specify the path to the generated .npz file.
```python
CALIB_FILE = "calibration_images/xxxx/stereo_calibration_result.npz"
```

## 注意 / Notes
キャリブレーション後はカメラ位置を動かさないでください  
Do not move the cameras after calibration.

チェスボードは様々な角度から撮影してください  
Capture the chessboard from various angles and distances.

照明環境によって色検出の精度が変わります  
Lighting conditions may affect color detection accuracy.

## フォルダ構成 / Folder Structure
```text
PoseRingTest/
├─ capture_calibration_pairs.py
├─ stereo_calibrate_from_saved_pairs.py
├─ green_3d_from_calibration.py
├─ four_color_3d_target_game.py
├─ yellow_3d_ble_led_test.py
├─ xiao_ble_led_receiver.ino
├─ camera_check_2cam.py
├─ camera_index_check.py
├─ calibration_images/
└─ archive/
```

## 現在の進捗 / Current Progress
**2026/05/01**  
  
1.プログラムを改善  
・キャリブレーションの際、動いている間は保存せず、静止してから保存  
・sキーで4色の現在座標を同時に目標として保存  
・4色すべてが目標範囲内に入るとCLEAR  
・色を見失った場合は最後に検出した座標を使用  
  
2.黄色マーカーのみのBLE LEDフィードバックに成功  
・黄色がゴール範囲内に入ると、PCからXIAO nRF52840 SenseへBLE送信  
・XIAOの内蔵LEDが点灯  
・黄色がゴール範囲外に出るとLED消灯  
\
\
**2026/05/04**


**4台カメラ版の実装 / Four-camera version**  
  
2台カメラによるステレオ計測を2セット用意し、合計4台のカメラを使用する版を実装しました。  
- Aセット：通常使用するメインのステレオカメラ  
- Bセット：Aセットでマーカーが見えない場合に補助するステレオカメラ
```bash
four_camera_3d_target_game.py
```
AセットとBセットは別々にステレオキャリブレーションを行っています。  
そのため、A/Bの3D座標系は直接混ぜず、以下のルールで判定しています。  
  
1. Aセットで検出できている場合  
   → Aセットの現在座標とAセットの目標座標を比較  
  
2. Aセットで検出できず、Bセットで検出できている場合  
   → Bセットの現在座標とBセットの目標座標を比較  
  
3. AセットでもBセットでも検出できない場合  
   → 最後に使用した座標を短時間だけ使用  
  
This project now supports a four-camera version using two stereo camera sets.  

Set A: main stereo camera pair  
Set B: backup stereo camera pair used when markers are lost in Set A  

The coordinate systems of Set A and Set B are not directly mixed.  
Each marker is judged using either Set A coordinates or Set B coordinates depending on visibility.  

  
**2026/05/06**
**赤マーカーのLEDリング・音フィードバック / Red marker LED ring and sound feedback**
```bash
redlight_ring.py
```
赤マーカーを対象として、現在位置と保存した目標位置との距離を計算し、  
距離に応じてNeoPixel LEDリングの赤色の強さを変化させます。  
  
主な動作は以下です。  
  
・BLE接続中はLEDリングが白色に点灯  
・赤マーカーが目標位置に近づくほど、LEDリングが白から赤へ変化  
・赤マーカーがゴール判定内に入ると、PC側から最大値255を送信  
・XIAO側では、250以上の値をゴール判定内として扱い、赤色点滅を開始  
・ゴール判定内に3秒間入り続けると、DFPlayer Miniから効果音を再生  
・ゴール判定外に出ると、3秒カウントはリセットされる  

The redlight_ring.py program integrates BLE feedback into the four-camera 3D target game.  

It uses the red marker as the feedback target.  
The distance between the current red marker position and the saved target position is converted into a BLE value from 2 to 255.  
The XIAO nRF52840 Sense receives this value and changes the NeoPixel LED ring from white to red as the marker approaches the target.  

Main behavior:  
   
- White LED while BLE is connected  
- Gradual transition from white to red as the red marker approaches the target  
- Sends 255 when the red marker enters the goal area  
- The XIAO treats values of 250 or higher as being inside the goal  
- The LED ring blinks red while the marker remains inside the goal  
- After staying inside the goal for 3 seconds, a sound effect is played using DFPlayer Mini  
- If the marker leaves the goal area, the 3-second timer is reset  

**XIAO nRF52840 Sense側のプログラム / Device-side firmware**
```bash
RED_blightness_D.ino
```
XIAO nRF52840 Senseには、事前に RED_blightness_D.ino を書き込んでおく必要があります。

このArduinoスケッチでは、PC側からBLEで受け取る値を以下のように扱います。

0 = 消灯  
1 = BLE接続中の白色表示  
2〜255 = 赤色LEDの輝度  
250〜255 = ゴール判定内として扱う  

The XIAO nRF52840 Sense must be programmed with RED_blightness_D.ino before running redlight_ring.py.  

The Arduino sketch interprets BLE values as follows:  

0 = LED off  
1 = white LED while BLE is connected  
2-255 = red LED brightness  
250-255 = treated as inside the goal area  


