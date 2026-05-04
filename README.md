# PoseRingTest

## 概要 / Overview
2台のカメラを用いてステレオキャリブレーションを行い、  
マーカーの3次元位置を計測するプログラムです。

現在は、赤・黄・青・緑の4色マーカーの3D座標検出と、  
黄色マーカーのみを対象としたXIAO nRF52840 SenseへのBLE LEDフィードバックの動作確認まで成功しています。  

This project performs stereo camera calibration using two cameras  
and computes the 3D positions of colored markers via triangulation.

Currently, the project supports 3D detection of red, yellow, blue, and green markers,  
and a BLE LED feedback test using XIAO nRF52840 Sense for the yellow marker.


---

## 必要環境 / Requirements
- Windows（動作確認済み / Verified）
- Python 3.10 +
- USB cameras × 2
- XIAO nRF52840 Sense（BLE LEDフィードバックを使う場合）
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

`four_color_3d_target_game_ble_yellow_only.py` を使う場合、XIAO nRF52840 Senseには  
事前に `xiao_ble_led_receiver.ino` を書き込んでおく必要があります。  

このスケッチでは、XIAOを `PoseRing_YELLOW` という名前のBLEデバイスとして動作させます。  
PC側PythonからBLEで `1` を受信すると内蔵LEDを点灯し、`0` を受信すると消灯します。  

XIAO nRF52840 Senseの内蔵LEDは `LOW` で点灯、`HIGH` で消灯します。  
  
  
When using `four_color_3d_target_game_ble_yellow_only.py`,   
you must first upload `xiao_ble_led_receiver.ino` to the XIAO nRF52840 Sense.   

In this sketch, the XIAO operates as a BLE device named `PoseRing_YELLOW`.  
When Python on the PC receives a `1` via BLE, the built-in LED turns on; when it receives a `0`, the LED turns off.  

The built-in LED on the XIAO nRF52840 Sense turns on when set to `LOW` and turns off when set to `HIGH`.  



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

### ④ 黄色マーカーのBLE LEDフィードバック / Yellow marker BLE LED feedback 
```bash
yellow_3d_ble_led_test.py
```
このプログラムでは、黄色マーカーのみを検出し、  
黄色が設定したゴール位置に入ったとき、PCからBLE通信でXIAO nRF52840 Senseへ信号を送り、  
内蔵LEDを点灯させます。
現在、この黄色のみのBluetooth版は動作確認済みです。  

**注意：XIAO側には、BLEデバイス名 PoseRing_YELLOW として動作するArduinoプログラムを書き込んでおく必要があります。**  
  
In this program, only yellow markers are detected,  
and when the yellow marker enters the designated goal position,   
a signal is sent from the PC to the XIAO nRF52840 Sense via BLE, causing the built-in LED to light up.  
Currently, this Bluetooth version that detects only yellow has been verified to work.  

Note: You must upload an Arduino program to the XIAO so that it operates with the BLE device name “PoseRing_YELLOW”.  

  

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
**2026/05/04**\


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
  


