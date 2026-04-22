# PoseRingTest

## 概要
2台のカメラを用いてステレオキャリブレーションを行い、  
緑色マーカーの3次元位置を計測するプログラムです。

キャリブレーション画像を取得し、カメラの内部・外部パラメータを推定した後、  
緑色マーカーの位置を各カメラ画像から検出し、三角測量によって3次元座標を求めます。

---

## 必要環境
- Windows（動作確認済み）
- Python 3.10 以上
- USBカメラ 2台

---

## 必要ライブラリ
以下をインストールしてください。

```bash
pip install opencv-python numpy
```

## 実行手順
① キャリブレーション画像の取得
python capture_calibration_pairs.py

→ calibration_images フォルダに画像が保存されます

② ステレオキャリブレーション
python stereo_calibrate_from_saved_pairs.py

→ キャリブレーション結果（.npz ファイル）が生成されます

③ 3D計測
python green_3d_from_calibration.py

→ 緑色マーカーの3次元座標が計算されます

## 事前に変更が必要な箇所
カメラインデックス

環境によってカメラ番号が異なるため、必要に応じて変更してください。

CAM0_INDEX = 0
CAM1_INDEX = 1
セッションフォルダ

キャリブレーションで保存されたフォルダを指定してください。

SESSION_DIR = "calibration_images/xxxx"
キャリブレーションファイル

生成された .npz ファイルのパスを指定してください。

CALIB_FILE = "calibration_images/xxxx/stereo_calibration_result.npz"

## 注意
キャリブレーション後はカメラ位置を動かさないでください
チェスボードは様々な角度から撮影してください
照明環境によって色検出の精度が変わります

## フォルダ構成
PoseRingTest/
├─ capture_calibration_pairs.py
├─ stereo_calibrate_from_saved_pairs.py
├─ green_3d_from_calibration.py
├─ camera_check_2cam.py
├─ camera_index_check.py
├─ calibration_images/
└─ archive/
