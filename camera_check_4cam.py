import cv2
import numpy as np
import os
import time

# =========================
# 設定
# =========================
CHECK_INDICES = list(range(0, 10))

VIEW_W = 400
VIEW_H = 350

CAPTURE_W = 320
CAPTURE_H = 240
FPS = 15

SAVE_DIR = "camera_check_4cam_default_result"


def open_camera(index):
    """
    DSHOW backendで強制的にカメラを開く。
    """
    # ★ ここに cv2.CAP_DSHOW を追加する ★
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)

    if not cap.isOpened():
        cap.release()
        return None

    # 解像度とFPSの設定（DSHOWの場合は少しフォーマット指定も足すと安定します）
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_H)
    cap.set(cv2.CAP_PROP_FPS, FPS)

    ok_count = 0
    last_frame = None

    for _ in range(20):
        ret, frame = cap.read()
        if ret and frame is not None:
            ok_count += 1
            last_frame = frame

    if ok_count == 0:
        cap.release()
        return None

    return cap


def brightness(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray))


def make_grid(frames, labels, cols=2):
    resized = []

    for frame, label in zip(frames, labels):
        view = cv2.resize(frame, (VIEW_W, VIEW_H))

        cv2.rectangle(view, (0, 0), (VIEW_W, 40), (0, 0, 0), -1)
        cv2.putText(
            view,
            label,
            (8, 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 255),
            2
        )

        resized.append(view)

    if len(resized) == 0:
        blank = np.zeros((VIEW_H, VIEW_W, 3), dtype=np.uint8)
        cv2.putText(blank, "No Camera", (40, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        return blank

    rows = int(np.ceil(len(resized) / cols))
    total_cells = rows * cols

    while len(resized) < total_cells:
        resized.append(np.zeros((VIEW_H, VIEW_W, 3), dtype=np.uint8))

    grid_rows = []
    for r in range(rows):
        row = np.hstack(resized[r * cols:(r + 1) * cols])
        grid_rows.append(row)

    return np.vstack(grid_rows)


def save_snapshots(caps, indices):
    os.makedirs(SAVE_DIR, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    session_dir = os.path.join(SAVE_DIR, f"check_{timestamp}")
    os.makedirs(session_dir, exist_ok=True)

    with open(os.path.join(session_dir, "camera_indices.txt"), "w", encoding="utf-8") as f:
        f.write("Detected camera indices by DEFAULT backend\n")
        f.write("=========================================\n")

        for i, idx in enumerate(indices):
            f.write(f"Camera view {i}: index {idx}\n")

        if len(indices) >= 4:
            f.write("\nRecommended example:\n")
            f.write(f"A set: CAM0_INDEX={indices[0]}, CAM1_INDEX={indices[1]}\n")
            f.write(f"B set: CAM0_INDEX={indices[2]}, CAM1_INDEX={indices[3]}\n")

    for idx, cap in zip(indices, caps):
        ret, frame = cap.read()
        if ret and frame is not None:
            filename = os.path.join(session_dir, f"camera_index_{idx}.png")
            cv2.imwrite(filename, frame)

    print("スナップショットを保存しました:")
    print(session_dir)


def main():
    print("======================================")
    print("4 Camera Index Check DEFAULT")
    print("capture_calibration_pairs.py と同じ方式で開きます")
    print("q / Esc : 終了")
    print("s       : 現在画像を保存")
    print("======================================")

    caps = []
    indices = []

    for idx in CHECK_INDICES:
        print(f"Checking camera index {idx} with DEFAULT ...")
        cap = open_camera(idx)

        if cap is not None:
            ret, frame = cap.read()
            b = brightness(frame) if ret and frame is not None else 0.0

            print(f"  OK: camera index {idx}, brightness={b:.1f}")
            caps.append(cap)
            indices.append(idx)
        else:
            print(f"  NG: camera index {idx}")

    if len(caps) == 0:
        print("使用可能なカメラが見つかりませんでした。")
        return

    print("======================================")
    print("検出されたカメラ番号:")
    print(indices)

    if len(indices) >= 4:
        print("4台以上見つかりました。")
        print(f"Aセット候補: {indices[0]}, {indices[1]}")
        print(f"Bセット候補: {indices[2]}, {indices[3]}")
    else:
        print("注意: 4台未満です。")
    print("======================================")

    while True:
        frames = []
        labels = []

        for idx, cap in zip(indices, caps):
            ret, frame = cap.read()

            if ret and frame is not None:
                b = brightness(frame)
                frames.append(frame)
                labels.append(f"Index {idx} | bright={b:.1f}")
            else:
                blank = np.zeros((CAPTURE_H, CAPTURE_W, 3), dtype=np.uint8)
                cv2.putText(blank, f"Index {idx}: frame error", (50, 240),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
                frames.append(blank)
                labels.append(f"Index {idx} ERROR")

        display = make_grid(frames, labels, cols=2)

        info_panel = np.zeros((90, display.shape[1], 3), dtype=np.uint8)

        cv2.putText(
            info_panel,
            "DEFAULT backend | q/Esc: quit | s: save snapshots",
            (15, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2
        )

        cv2.putText(
            info_panel,
            f"Detected indices: {indices}",
            (15, 70),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2
        )

        display = np.vstack((display, info_panel))
        cv2.imshow("4 Camera Index Check DEFAULT", display)

        key = cv2.waitKey(1) & 0xFF

        if key == ord("q") or key == 27:
            break

        if key == ord("s"):
            save_snapshots(caps, indices)

    for cap in caps:
        cap.release()

    cv2.destroyAllWindows()
    print("終了しました。")


if __name__ == "__main__":
    main()