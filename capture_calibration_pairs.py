import cv2
import numpy as np
import os
import time

# =========================
# 設定
# =========================
CAM0_INDEX = 2                  # ノートPC内蔵カメラ
CAM1_INDEX = 3                  # iPhone (DroidCam)
PATTERN_SIZE = (9, 6)           # 内側の交点数 (9 x 6)
START_DELAY_SEC = 10             # 何秒後に自動撮影を始めるか
CAPTURE_INTERVAL_SEC = 3.0      # 何秒おきに保存するか
TARGET_PAIRS = 30               # 保存したいペア数
MIN_CORNER_SHIFT = 18.0         # 前回と似すぎる姿勢を避けるためのしきい値
WINDOW_NAME = "Stereo Calibration Capture"

# =========================
# 保存先作成
# =========================
session_name = time.strftime("calib_%Y%m%d_%H%M%S")
root_dir = os.path.join("calibration_images", session_name)
cam0_dir = os.path.join(root_dir, "cam0")
cam1_dir = os.path.join(root_dir, "cam1")
os.makedirs(cam0_dir, exist_ok=True)
os.makedirs(cam1_dir, exist_ok=True)

# メタ情報保存
with open(os.path.join(root_dir, "session_info.txt"), "w", encoding="utf-8") as f:
    f.write(f"PATTERN_SIZE={PATTERN_SIZE}\n")
    f.write(f"START_DELAY_SEC={START_DELAY_SEC}\n")
    f.write(f"CAPTURE_INTERVAL_SEC={CAPTURE_INTERVAL_SEC}\n")
    f.write(f"TARGET_PAIRS={TARGET_PAIRS}\n")
    f.write(f"MIN_CORNER_SHIFT={MIN_CORNER_SHIFT}\n")
    f.write(f"CAM0_INDEX={CAM0_INDEX}\n")
    f.write(f"CAM1_INDEX={CAM1_INDEX}\n")

# =========================
# カメラ開始
# =========================
cap0 = cv2.VideoCapture(CAM0_INDEX)
cap1 = cv2.VideoCapture(CAM1_INDEX)

if not cap0.isOpened():
    raise RuntimeError("カメラ0を開けませんでした。CAM0_INDEX を確認してください。")

if not cap1.isOpened():
    raise RuntimeError("カメラ1を開けませんでした。CAM1_INDEX を確認してください。")

for cap in [cap0, cap1]:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

# チェッカーボード角検出のための設定
criteria = (
    cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
    30,
    0.001
)

flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE

def find_board(gray):
    """
    チェッカーボード検出
    成功: ret=True, corners
    失敗: ret=False, None
    """
    ret, corners = cv2.findChessboardCorners(gray, PATTERN_SIZE, flags)
    if ret:
        corners = cv2.cornerSubPix(
            gray,
            corners,
            (11, 11),
            (-1, -1),
            criteria
        )
    return ret, corners

def draw_board(frame, ret, corners):
    """
    検出結果を描画
    """
    out = frame.copy()
    if ret:
        cv2.drawChessboardCorners(out, PATTERN_SIZE, corners, ret)
    return out

def board_pose_changed(corners0, corners1, last_corners0, last_corners1, min_shift):
    """
    前回保存した姿勢と比べて、十分変化があるか判定
    """
    if last_corners0 is None or last_corners1 is None:
        return True

    c0 = corners0.reshape(-1, 2)
    c1 = corners1.reshape(-1, 2)
    l0 = last_corners0.reshape(-1, 2)
    l1 = last_corners1.reshape(-1, 2)

    shift0 = np.mean(np.linalg.norm(c0 - l0, axis=1))
    shift1 = np.mean(np.linalg.norm(c1 - l1, axis=1))

    return max(shift0, shift1) >= min_shift

saved_count = 0
last_save_time = 0.0
last_corners0 = None
last_corners1 = None
prev_corners0 = None  # フレーム間の移動量計算用
prev_corners1 = None  # フレーム間の移動量計算用

start_time = time.time()
message = "Starting..."

print("======================================")
print("キャリブレーション画像の自動保存を開始します")
print(f"保存先: {root_dir}")
print(f"{START_DELAY_SEC} 秒後に自動撮影開始")
print("q または Esc で終了")
print("======================================")

while True:
    ret0, frame0 = cap0.read()
    ret1, frame1 = cap1.read()

    if not ret0 or not ret1:
        print("フレーム取得に失敗しました。")
        break

    # 生画像のまま処理
    gray0 = cv2.cvtColor(frame0, cv2.COLOR_BGR2GRAY)
    gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)

    found0, corners0 = find_board(gray0)
    found1, corners1 = find_board(gray1)

    vis0 = draw_board(frame0, found0, corners0)
    vis1 = draw_board(frame1, found1, corners1)

    now = time.time()
    elapsed = now - start_time

    # ======================================
    # 状態判定と保存処理
    # ======================================
    if elapsed < START_DELAY_SEC:
        remain = START_DELAY_SEC - elapsed
        message = f"Countdown: {remain:.1f} sec"
        last_save_time = now  # 待機中はタイマーを進めない
    else:
        if not found0 or not found1:
            last_save_time = now  # ボードが見えない場合はタイマーリセット
            if not found0 and not found1:
                message = "Board not found in both cameras"
            elif not found0:
                message = "Board not found in Camera 0"
            else:
                message = "Board not found in Camera 1"
        else:
            # 両方のカメラで見つかった場合
            enough_change = board_pose_changed(
                corners0, corners1,
                last_corners0, last_corners1,
                MIN_CORNER_SHIFT
            )

            # 動いているか（手ブレ・モーションブラー）の判定
            is_moving = False
            if prev_corners0 is not None and prev_corners1 is not None:
                c0 = corners0.reshape(-1, 2)
                p0 = prev_corners0.reshape(-1, 2)
                c1 = corners1.reshape(-1, 2)
                p1 = prev_corners1.reshape(-1, 2)
                if c0.shape == p0.shape and c1.shape == p1.shape:
                    shift0 = np.mean(np.linalg.norm(c0 - p0, axis=1))
                    shift1 = np.mean(np.linalg.norm(c1 - p1, axis=1))
                    # フレーム間で平均2.5px以上動いていたら「移動中」とみなす
                    if max(shift0, shift1) > 2.5:
                        is_moving = True

            # 状態に応じたタイマーのリセットと進行
            if not enough_change:
                last_save_time = now  # 同じ場所すぎるのでタイマーリセット
                message = "Move board more (too similar to last pose)"
            elif is_moving:
                last_save_time = now  # ボードが動いているのでタイマーリセット
                message = "Moving... Hold completely still"
            else:
                # 新しい場所で、かつ「完全に静止している」場合のみタイマーが進む
                time_since_stable = now - last_save_time
                if time_since_stable >= CAPTURE_INTERVAL_SEC:
                    if saved_count < TARGET_PAIRS:
                        filename0 = os.path.join(cam0_dir, f"pair_{saved_count:03d}_cam0.png")
                        filename1 = os.path.join(cam1_dir, f"pair_{saved_count:03d}_cam1.png")

                        # 反転していない「生画像」を保存
                        cv2.imwrite(filename0, frame0)
                        cv2.imwrite(filename1, frame1)

                        last_save_time = now
                        last_corners0 = corners0.copy()
                        last_corners1 = corners1.copy()
                        saved_count += 1
                        message = f"Saved pair {saved_count}/{TARGET_PAIRS}"
                        print(message)
                else:
                    if saved_count >= TARGET_PAIRS:
                        message = "Target reached. Press q to quit."
                    else:
                        wait_sec = CAPTURE_INTERVAL_SEC - time_since_stable
                        message = f"Hold still... Capturing in {wait_sec:.1f} sec"

    # フレーム間移動量計算のために、現在のコーナーを保存しておく
    prev_corners0 = corners0.copy() if found0 else None
    prev_corners1 = corners1.copy() if found1 else None

    # ======================================
    # 画面表示用の処理（ここで初めて反転）
    # ======================================
    disp0 = cv2.flip(vis0, 1)
    disp1 = cv2.flip(vis1, 1)

    # 鏡文字にならないように、反転後の画像にテキストを描画
    cv2.putText(disp0, f"Camera 0 | found={found0}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0) if found0 else (0, 0, 255), 2)
    cv2.putText(disp1, f"Camera 1 | found={found1}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0) if found1 else (0, 0, 255), 2)

    # 2画面を横に並べる
    combined = np.hstack((disp0, disp1))

    # 下に情報欄を追加
    info_panel = np.zeros((120, combined.shape[1], 3), dtype=np.uint8)
    cv2.putText(info_panel, f"Saved: {saved_count}/{TARGET_PAIRS}", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
    
    # メッセージの色を状態によって変える
    msg_color = (255, 255, 255)
    if "Moving" in message or "too similar" in message or "not found" in message:
        msg_color = (0, 150, 255) # オレンジ
    elif "Hold still" in message:
        msg_color = (0, 255, 255) # 黄色
    elif "Saved pair" in message:
        msg_color = (0, 255, 0)   # 緑

    cv2.putText(info_panel, message, (20, 90),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, msg_color, 2)

    display = np.vstack((combined, info_panel))
    cv2.imshow(WINDOW_NAME, display)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q") or key == 27:
        break

cap0.release()
cap1.release()
cv2.destroyAllWindows()

print("終了しました。")
print(f"保存先: {root_dir}")