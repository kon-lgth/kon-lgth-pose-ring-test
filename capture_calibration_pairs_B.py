import cv2
import numpy as np
import os
import time

# =========================
# Bセット用 設定
# =========================
# 今回検出されたカメラ番号 [1, 2, 4, 5] のうち、
# まずBセットとして Index 4 と Index 5 を使う
CAM0_INDEX = 0
CAM1_INDEX = 3

PATTERN_SIZE = (9, 6)           # チェッカーボード内側の交点数
START_DELAY_SEC = 10            # 何秒後に自動撮影を始めるか
CAPTURE_INTERVAL_SEC = 3.0      # 何秒おきに保存するか
TARGET_PAIRS = 30               # 保存したいペア数
MIN_CORNER_SHIFT = 18.0         # 前回と似すぎる姿勢を避けるためのしきい値
WINDOW_NAME = "Stereo Calibration Capture B"

# WindowsではDirectShowの方が安定することが多い
USE_DSHOW = True

# =========================
# 保存先作成
# =========================
session_name = time.strftime("calib_B_%Y%m%d_%H%M%S")
root_dir = os.path.join("calibration_images", session_name)
cam0_dir = os.path.join(root_dir, "cam0")
cam1_dir = os.path.join(root_dir, "cam1")
os.makedirs(cam0_dir, exist_ok=True)
os.makedirs(cam1_dir, exist_ok=True)

# メタ情報保存
with open(os.path.join(root_dir, "session_info.txt"), "w", encoding="utf-8") as f:
    f.write("Stereo calibration capture for B set\n")
    f.write("====================================\n")
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
def open_camera(index):
    if USE_DSHOW:
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(index)

    if not cap.isOpened():
        raise RuntimeError(f"カメラ index={index} を開けませんでした。")

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 15)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    return cap


cap0 = open_camera(CAM0_INDEX)
cap1 = open_camera(CAM1_INDEX)

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
prev_corners0 = None
prev_corners1 = None

start_time = time.time()
message = "Starting..."

print("======================================")
print("Bセット用キャリブレーション画像の自動保存を開始します")
print(f"CAM0_INDEX: {CAM0_INDEX}")
print(f"CAM1_INDEX: {CAM1_INDEX}")
print(f"保存先: {root_dir}")
print(f"{START_DELAY_SEC} 秒後に自動撮影開始")
print("q または Esc で終了")
print("======================================")

while True:
    ret0, frame0 = cap0.read()
    ret1, frame1 = cap1.read()

    if not ret0 or frame0 is None:
        print("カメラ0のフレーム取得に失敗しました。")
        break

    if not ret1 or frame1 is None:
        print("カメラ1のフレーム取得に失敗しました。")
        break

    # 生画像のまま処理する
    gray0 = cv2.cvtColor(frame0, cv2.COLOR_BGR2GRAY)
    gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)

    found0, corners0 = find_board(gray0)
    found1, corners1 = find_board(gray1)

    vis0 = draw_board(frame0, found0, corners0)
    vis1 = draw_board(frame1, found1, corners1)

    now = time.time()
    elapsed = now - start_time

    # =========================
    # 状態判定と保存処理
    # =========================
    if elapsed < START_DELAY_SEC:
        remain = START_DELAY_SEC - elapsed
        message = f"Countdown: {remain:.1f} sec"
        last_save_time = now
    else:
        if not found0 or not found1:
            last_save_time = now

            if not found0 and not found1:
                message = "Board not found in both cameras"
            elif not found0:
                message = "Board not found in Camera 0"
            else:
                message = "Board not found in Camera 1"

        else:
            enough_change = board_pose_changed(
                corners0,
                corners1,
                last_corners0,
                last_corners1,
                MIN_CORNER_SHIFT
            )

            # 動いているかどうかを確認
            is_moving = False

            if prev_corners0 is not None and prev_corners1 is not None:
                c0 = corners0.reshape(-1, 2)
                p0 = prev_corners0.reshape(-1, 2)
                c1 = corners1.reshape(-1, 2)
                p1 = prev_corners1.reshape(-1, 2)

                if c0.shape == p0.shape and c1.shape == p1.shape:
                    shift0 = np.mean(np.linalg.norm(c0 - p0, axis=1))
                    shift1 = np.mean(np.linalg.norm(c1 - p1, axis=1))

                    if max(shift0, shift1) > 2.5:
                        is_moving = True

            if not enough_change:
                last_save_time = now
                message = "Move board more"

            elif is_moving:
                last_save_time = now
                message = "Moving... Hold still"

            else:
                time_since_stable = now - last_save_time

                if saved_count >= TARGET_PAIRS:
                    message = "Target reached. Press q to quit."

                elif time_since_stable >= CAPTURE_INTERVAL_SEC:
                    filename0 = os.path.join(cam0_dir, f"pair_{saved_count:03d}_cam0.png")
                    filename1 = os.path.join(cam1_dir, f"pair_{saved_count:03d}_cam1.png")

                    # 反転していない生画像を保存
                    cv2.imwrite(filename0, frame0)
                    cv2.imwrite(filename1, frame1)

                    last_save_time = now
                    last_corners0 = corners0.copy()
                    last_corners1 = corners1.copy()
                    saved_count += 1

                    message = f"Saved pair {saved_count}/{TARGET_PAIRS}"
                    print(message)

                else:
                    wait_sec = CAPTURE_INTERVAL_SEC - time_since_stable
                    message = f"Hold still... Capturing in {wait_sec:.1f} sec"

    # フレーム間移動量確認用
    prev_corners0 = corners0.copy() if found0 else None
    prev_corners1 = corners1.copy() if found1 else None

    # =========================
    # 表示用
    # =========================
    disp0 = cv2.flip(vis0, 1)
    disp1 = cv2.flip(vis1, 1)

    cv2.putText(
        disp0,
        f"B Cam0 | Index {CAM0_INDEX} | found={found0}",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0) if found0 else (0, 0, 255),
        2
    )

    cv2.putText(
        disp1,
        f"B Cam1 | Index {CAM1_INDEX} | found={found1}",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0) if found1 else (0, 0, 255),
        2
    )

    combined = np.hstack((disp0, disp1))

    info_panel = np.zeros((130, combined.shape[1], 3), dtype=np.uint8)

    cv2.putText(
        info_panel,
        f"B SET Calibration | Saved: {saved_count}/{TARGET_PAIRS}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 255, 255),
        2
    )

    msg_color = (255, 255, 255)
    if "not found" in message or "Move" in message or "Moving" in message:
        msg_color = (0, 150, 255)
    elif "Hold" in message:
        msg_color = (0, 255, 255)
    elif "Saved" in message:
        msg_color = (0, 255, 0)

    cv2.putText(
        info_panel,
        message,
        (20, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        msg_color,
        2
    )

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