# PoseRingTest

## 概要 / Overview
2台のカメラを用いてステレオキャリブレーションを行い、  
緑色マーカーの3次元位置を計測するプログラムです。

キャリブレーション画像を取得し、カメラの内部・外部パラメータを推定した後、  
緑色マーカーの位置を各カメラ画像から検出し、三角測量によって3次元座標を求めます。　　

This project performs stereo camera calibration using two cameras  
and computes the 3D position of a green marker via triangulation.

---

## 必要環境 / Requirements
- Windows（動作確認済み / Verified）
- Python 3.10 +
- USB cameras × 2
---

## 必要ライブラリ / Required Libraries
以下をインストールしてください。
Install the following packages:

```bash
pip install opencv-python numpy
```

## 実行手順 / How to Run
① キャリブレーション画像の取得 / Capture calibration image pairs
```bash
capture_calibration_pairs.py
```
→ calibration_images フォルダに画像が保存されます  
→ Calibration image pairs will be saved in the calibration_images folder.

② ステレオキャリブレーション / Stereo calibration
```bash
stereo_calibrate_from_saved_pairs.py
```
→ キャリブレーション結果（.npz ファイル）が生成されます  
→ A .npz calibration file will be generated.

③ 3D計測 / 3D measurement
```bash
green_3d_from_calibration.py
```
→ 緑色マーカーの3次元座標が計算されます  
→ Computes the 3D coordinates of the green marker.

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
├─ camera_check_2cam.py
├─ camera_index_check.py
├─ calibration_images/
└─ archive/
```

## 現在の進捗(5/1)：黄色マーカーの3D座標判定とXIAO LEDのBLE制御

現在、XIAO nRF52840 SenseをBLEデバイスとして動作させ、PC側のPythonプログラムからBLE通信でLED点灯・消灯命令を送信できるようにした。

### 成功した動作

1. 2台カメラで黄色マーカーを検出
2. ステレオキャリブレーション結果を用いて黄色マーカーの3D座標を計算
3. Enterキーで現在の黄色位置を原点に設定
4. sキーで現在の黄色位置をゴール座標として保存
5. 黄色マーカーがゴール範囲内に入ると、PCからXIAOへBLEで信号を送信
6. XIAO nRF52840 Senseの内蔵LEDが点灯
7. 黄色マーカーがゴール範囲外に出るとLEDが消灯

### 使用ファイル

- `yellow_3d_ble_led_test.py`

### 必要なPythonライブラリ

```bash
pip install opencv-python numpy bleak


