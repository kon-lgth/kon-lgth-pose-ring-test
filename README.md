# PoseRingTest

[English version](README_en.md)

## 概要

2台のカメラを用いてステレオキャリブレーションを行い、マーカーの3次元位置を計測するプログラムです。

現在は、赤・黄・青・緑の4色マーカーの3D座標検出、2PC構成によるA/Bセットの統合判定、XIAO nRF52840 SenseへのBLE LEDフィードバック、ゴール音再生、クリア時間計測、出題時/クリア時写真保存、クリア後の比較画像表示まで実装・動作確認しています。

2026/05/09時点で、AセットとBセットを別々のノートPCで処理する2PC構成を実装し、Wi-Fi / UDP通信によってBセットの3D座標をメインPCへ送信できることを確認しました。2026/05/10時点では、メインPC側の正式実行ファイル `redlight_ring_2pc_main.py` を、写真保存・クリア時間計測・ステージ内外LED制御を含む版に更新しています。

---

## 必要環境

- Windows（動作確認済み）
- Python 3.10+
- USBカメラ × 2
- XIAO nRF52840 Sense（BLE LEDフィードバックを使う場合）
- NeoPixel LED Ring（リング用）
- DFPlayer Mini（リングのゴール音用）

---

## 必要ライブラリ

以下をインストールしてください。

```bash
pip install opencv-python numpy
```

BLE通信を使う場合は、以下もインストールしてください。

```bash
pip install bleak
```

---

## XIAO nRF52840 Sense 側のBLE LED受信プログラム

`redlight_ring.py` または `redlight_ring_2pc_main.py` を使う場合、XIAO nRF52840 Senseには事前に `RED_blightness_D.ino` を書き込んでおく必要があります。現在の `RED_blightness_D.ino` は、`RED_blightness_D_volume.ino` の内容を正式版として反映したもので、DFPlayer Miniの爆音対策を含みます。

このスケッチでは、XIAOを `PoseRing_YELLOW` という名前のBLEデバイスとして動作させます。

BLE受信値の意味は以下です。

- `0`：消灯
- `1`：BLE接続中、またはステージ内での白色表示
- `2〜255`：赤色LEDの輝度
- `250〜255`：ゴール判定内として扱う（赤点滅＋3秒で音再生）

DFPlayer Miniの効果音については、時々想定より大きい音で鳴る問題を避けるため、起動時だけでなく再生直前にも安全音量へ再設定してから再生します。

XIAO nRF52840 Senseの内蔵LEDは `LOW` で点灯、`HIGH` で消灯します。

---

## 実行手順

### ① キャリブレーション画像の取得

```bash
python capture_calibration_pairs.py
```

`calibration_images` フォルダにキャリブレーション画像が保存されます。

`capture_calibration_pairs.py` は、以下の改善を含む版です。

- 両カメラでチェッカーボードが検出できた場合のみ保存
- ボードが動いている間は保存しない
- 一定時間静止したときのみ保存

### ② ステレオキャリブレーション

```bash
python stereo_calibrate_from_saved_pairs.py
```

キャリブレーション結果として `.npz` ファイルが生成されます。

### ③ 4色マーカーの3D計測

```bash
python four_color_3d_target_game.py
```

赤・黄・青・緑の各色マーカーの3次元座標が計算されます。

主な機能は以下です。

- 赤、黄、青、緑の4色を同時に検出
- ステレオキャリブレーション結果を用いて各色の3D座標を計算
- Enterキーで現在の赤マーカー位置を原点に設定
- `s` キーで現在の4色の3D座標を目標位置として保存
- 各色が目標位置から一定距離以内にあるかを判定
- 4色すべてが目標範囲内に一定時間入るとCLEAR表示
- 色を見失った場合は、最後に検出した3D座標を短時間使用

### ④ 赤マーカー LEDリング＋音フィードバック

```bash
python redlight_ring.py
```

このプログラムでは、赤色マーカーを検出し、赤色が設定したゴール位置に入ったとき、PCからBLE通信でXIAO nRF52840 Senseへ信号を送り、リングLEDを点灯させます。

現在、この赤色マーカー用のBLE版は動作確認済みです。

注意：XIAO側には、BLEデバイス名 `PoseRing_YELLOW` として動作するArduinoプログラムを書き込んでおく必要があります。

### ⑤ 2PC Wi-Fi / UDP構成

サブPCでBセット送信プログラムを実行します。

```bash
python sub_bset_udp_sender.py
```

メインPCで2PC統合版を実行します。

```bash
python redlight_ring_2pc_main.py
```

メインPC側のB_SET欄に `UDP age: 0.xx s` が表示されれば通信成功です。

現在の `redlight_ring_2pc_main.py` は、以前の `redlight_ring_2pc_main_step4_photo_capture.py` の内容を正式ファイル名に反映したものです。旧版の `redlight_ring_2pc_main.py` は `archive/` に退避して残します。

主なキー操作は以下です。

- `s`：A/B両方の現在4色座標を目標として保存し、出題時写真を保存する（まだゲーム開始しない）
- `g`：ゲーム開始、クリア時間計測スタート
- `c`：目標座標、ゲーム開始状態、CLEAR状態をリセット
- `r`：目標座標、最後に使った判定情報、ゲーム開始状態、CLEAR状態をすべてリセット
- `0 / 1 / 2`：BLEテスト送信
- `a`：BLE自動制御に戻す
- `q / Esc`：終了

追加された主な動作は以下です。

- カメラ画面外、つまりステージ外に出た場合はLEDリングを消灯
- ステージ内で対象色が見えている場合は白色に点灯
- 体などで一瞬遮蔽されても、一定時間はステージ内扱いとして白色点灯を維持
- `s` キーでお題座標を保存しても、`g` キーを押すまではゲーム開始しない
- `g` キーを押してからクリア時間を計測
- `s` キーでA Cam0の出題時写真を保存
- ALL CLEAR時にA Cam0のクリア時写真を保存
- クリア後に出題時写真とクリア時写真を横並びでモニター表示
- 比較画像は縦横比を保ち、モニターからはみ出しにくいサイズで表示

---

## 事前に変更が必要な箇所

### カメラインデックス

環境によってカメラ番号が異なるため、必要に応じて変更してください。

```python
CAM0_INDEX = 0
CAM1_INDEX = 1
```

2PC版では、メインPC側のAセットカメラ番号を以下のように変更します。

```python
A_CAM0_INDEX = 1
A_CAM1_INDEX = 2
```

### セッションフォルダ・キャリブレーションファイル

現在の版では、Aセット/Bセットともに、基本的には最新のキャリブレーションフォルダや `.npz` ファイルを自動で選択します。

そのため、通常は以下のようなパスを毎回手動で書き換える必要はありません。

```python
SESSION_DIR = "calibration_images/xxxx"
CALIB_FILE = "calibration_images/xxxx/stereo_calibration_result.npz"
A_CALIB_FILE = r"calibration_images\xxxx\stereo_calibration_result.npz"
```

2PC版では、メインPC側で以下の通信設定を使います。

```python
USE_B_SET = True
USE_REMOTE_B_SET = True
REMOTE_B_UDP_IP = "0.0.0.0"
REMOTE_B_UDP_PORT = 5005
```

特定のキャリブレーション結果を固定して使いたい場合は、コード内で手動指定に戻すこともできます。

### カメラの開き方

キャリブレーション時と実行時でカメラの開き方を揃える必要があります。

今回、Aセットはキャリブレーション時に通常の `cv2.VideoCapture(index)` で開いていたため、`redlight_ring_2pc_main.py` では以下の設定にする必要がありました。

```python
A_BACKEND = "DEFAULT"
```

`A_BACKEND = "DSHOW"` にすると、同じカメラインデックスでも別のカメラが開かれる場合があり、キャリブレーション結果と実際の映像が一致せず、補正後の映像が大きく歪むことがあります。

---

## 注意

- キャリブレーション後はカメラ位置を動かさないでください。
- チェッカーボードは様々な角度・距離から撮影してください。
- 照明環境によって色検出の精度が変わります。
- AセットとBセットは別々にキャリブレーションしているため、A/Bの3D座標系は直接混ぜないでください。
- Aで検出できている色はA座標系で、Bで補助する色はB座標系で判定します。

---

## フォルダ構成

```text
PoseRingTest/
├─ capture_calibration_pairs.py
├─ capture_calibration_pairs_B.py
├─ stereo_calibrate_from_saved_pairs.py
├─ stereo_calibrate_B.py
├─ four_color_3d_target_game.py
├─ redlight_ring.py
├─ redlight_ring_2pc_main.py          # メインPC用の正式版。step4写真保存版を反映
├─ sub_bset_udp_sender.py             # サブPC用BセットUDP送信
├─ RED_blightness_D.ino               # XIAO用正式版。volume対策版を反映
├─ calibration_images/
├─ pose_photos/                       # 出題時/クリア時/比較画像の保存先
└─ archive/                           # 旧版コードの退避先
   ├─ redlight_ring_2pc_main_before_stage_led.py
   └─ RED_blightness_D_before_volume.ino
```

---

## 現在の進捗

### 2026/05/01

#### プログラム改善

- キャリブレーションの際、動いている間は保存せず、静止してから保存
- `s` キーで4色の現在座標を同時に目標として保存
- 4色すべてが目標範囲内に入るとCLEAR
- 色を見失った場合は最後に検出した座標を使用

#### 黄色マーカーのみのBLE LEDフィードバックに成功

- 黄色がゴール範囲内に入ると、PCからXIAO nRF52840 SenseへBLE送信
- XIAOの内蔵LEDが点灯
- 黄色がゴール範囲外に出るとLED消灯

### 2026/05/04

#### 4台カメラ版の実装

2台カメラによるステレオ計測を2セット用意し、合計4台のカメラを使用する版を実装しました。

```bash
python four_camera_3d_target_game.py
```

- Aセット：通常使用するメインのステレオカメラ
- Bセット：Aセットでマーカーが見えない場合に補助するステレオカメラ

AセットとBセットは別々にステレオキャリブレーションを行っています。そのため、A/Bの3D座標系は直接混ぜず、以下のルールで判定しています。

1. Aセットで検出できている場合  
   → Aセットの現在座標とAセットの目標座標を比較

2. Aセットで検出できず、Bセットで検出できている場合  
   → Bセットの現在座標とBセットの目標座標を比較

3. AセットでもBセットでも検出できない場合  
   → 最後に使用した座標を短時間だけ使用

### 2026/05/06

#### 赤マーカーのLEDリング・音フィードバック

```bash
python redlight_ring.py
```

赤マーカーを対象として、現在位置と保存した目標位置との距離を計算し、距離に応じてNeoPixel LEDリングの赤色の強さを変化させます。

主な動作は以下です。

- BLE接続中はLEDリングが白色に点灯
- 赤マーカーが目標位置に近づくほど、LEDリングが白から赤へ変化
- 赤マーカーがゴール判定内に入ると、PC側から最大値255を送信
- XIAO側では、250以上の値をゴール判定内として扱い、赤色点滅を開始
- ゴール判定内に3秒間入り続けると、DFPlayer Miniから効果音を再生
- ゴール判定外に出ると、3秒カウントはリセットされる

#### XIAO nRF52840 Sense側のプログラム

```bash
RED_blightness_D.ino
```

XIAO nRF52840 Senseには、事前に `RED_blightness_D.ino` を書き込んでおく必要があります。

このArduinoスケッチでは、PC側からBLEで受け取る値を以下のように扱います。

- `0`：消灯
- `1`：BLE接続中の白色表示
- `2〜255`：赤色LEDの輝度
- `250〜255`：ゴール判定内として扱う

### 2026/05/09

#### 2PC Wi-Fi / UDP構成の実装

Wi-Fi通信で、AセットとBセットを別々のノートPCで処理する2PC構成を実装しました。

#### 構成

メインPC：

- Aセットカメラ2台の3D座標を計算
- サブPCからBセットの3D座標をUDPで受信
- Aで見失った色だけBセット座標で補助
- XIAO nRF52840 SenseへBLEでLEDフィードバックを送信

サブPC：

- Bセットカメラ2台の3D座標を計算
- Wi-Fi / UDPでメインPCへ座標JSONを送信

#### 使用ファイル

```bash
redlight_ring_2pc_main.py
```

- メインPC側で実行する2PC統合版
- Aセットカメラ処理、BセットUDP受信、最終判定、BLE送信を担当

```bash
sub_bset_udp_sender.py
```

- サブPC側で実行するBセット送信プログラム
- Bセットカメラ処理、3D座標計算、UDP送信を担当

#### 実行順

1. メインPCとサブPCを同じWi-Fiに接続する
2. サブPCで `sub_bset_udp_sender.py` を実行する
3. メインPCで `redlight_ring_2pc_main.py` を実行する
4. メインPC側でB_SET欄に `UDP age: 0.xx s` が表示されれば通信成功

#### 成功したこと

- 大学Wi-Fi上でサブPCからメインPCへUDP通信できた
- サブPCのBセット3D座標をメインPC側で受信できた
- メインPC側でAセットを優先し、Aで見失った色だけBセット座標で補助できた
- メインPCからXIAO nRF52840 SenseへのBLE LEDフィードバックも併用できた

#### キャリブレーションファイルの自動選択

キャリブレーションを行うたびに、コード内のフォルダ名や `.npz` ファイル名を手動で書き換える手間を減らすため、最新のキャリブレーションフォルダを自動で選択する処理を追加しました。

対応したファイルは以下です。

```bash
stereo_calibrate_from_saved_pairs.py
```

- `calibration_images` 内の最新のAセット撮影フォルダを自動で選択
- 対象フォルダ例：`calib_20260509_013021`
- 最新フォルダ内に `stereo_calibration_result.npz` を生成

```bash
stereo_calibrate_B.py
```

- `calibration_images` 内の最新のBセット撮影フォルダを自動で選択
- 対象フォルダ例：`calib_B_20260508_235747`
- 最新フォルダ内に `stereo_calibration_result.npz` を生成

```bash
redlight_ring_2pc_main.py
```

- 最新のAセット用 `stereo_calibration_result.npz` を自動で選択
- Aセットのキャリブレーションをやり直しても、コード内の `A_CALIB_FILE` を毎回書き換える必要がない

```bash
sub_bset_udp_sender.py
```

- 最新のBセット用 `stereo_calibration_result.npz` を自動で選択
- Bセットのキャリブレーションをやり直しても、コード内の `CALIB_FILE` を毎回書き換える必要がない

実行の流れは以下です。

Aセット：

```bash
python capture_calibration_pairs.py
python stereo_calibrate_from_saved_pairs.py
python redlight_ring_2pc_main.py
```

Bセット：

```bash
python capture_calibration_pairs_B.py
python stereo_calibrate_B.py
python sub_bset_udp_sender.py
```

注意点として、最新フォルダを自動で使用するため、失敗したキャリブレーションが最後に作成されている場合は、その失敗した結果を使用してしまう可能性があります。
失敗したキャリブレーションフォルダは削除するか、成功したキャリブレーションを最後に作成してから実行してください。

### 2026/05/10

#### メインPC側 `redlight_ring_2pc_main.py` の更新

`redlight_ring_2pc_main_step4_photo_capture.py` で動作確認した内容を、正式な実行ファイル名 `redlight_ring_2pc_main.py` に反映しました。以前の `redlight_ring_2pc_main.py` は削除せず、`archive/` に退避して残します。

追加・変更した主な機能は以下です。

- `s` キーはお題座標の保存と出題時写真保存のみを行い、ゲームは開始しない
- `g` キーでゲーム開始し、その時点からクリア時間を計測する
- ALL CLEAR時にクリア時間を固定表示する
- ステージ外、つまり対象リングがカメラ画面外に出た場合はLEDリングを消灯する
- ステージ内で対象リングが見えている場合はLEDリングを白色点灯する
- 体などで一瞬遮蔽された場合は、短時間だけ白色点灯を維持する
- ゲーム開始後、ゴールに近づくと距離に応じて赤色LEDフィードバックを行う
- 出題時写真とクリア時写真を保存する
- 写真保存にはA Cam0の画像のみを使用する
- クリア後に、出題時写真とクリア時写真を横並びにした比較画像を表示する
- 比較画像は縦横比を保ち、モニターに収まりやすいサイズに調整する

写真は以下のフォルダにセッション単位で保存されます。

```text
pose_photos/session_YYYYMMDD_HHMMSS/
```

保存される画像の例は以下です。

```text
challenge_pose_YYYYMMDD_HHMMSS.jpg
clear_pose_YYYYMMDD_HHMMSS.jpg
comparison_YYYYMMDD_HHMMSS.jpg
```

#### XIAO側 `RED_blightness_D.ino` の更新

`RED_blightness_D_volume.ino` で追加したDFPlayer Miniの音量対策を、正式な `RED_blightness_D.ino` に反映しました。以前の `RED_blightness_D.ino` は削除せず、`archive/` に退避して残します。

主な変更点は以下です。

- 安全音量 `DFPLAYER_SAFE_VOLUME` を追加
- 起動時にDFPlayer Miniの音量を安全音量へ設定
- 効果音を鳴らす直前にも、毎回安全音量を再設定
- 音量設定が反映されるまで短く待ってから再生
- 時々普段より大きな音で効果音が鳴る問題への対策を追加

音量が大きい場合は `DFPLAYER_SAFE_VOLUME` を小さくし、小さすぎる場合は少し上げて調整します。
