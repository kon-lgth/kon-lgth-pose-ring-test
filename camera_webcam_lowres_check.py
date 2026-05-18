import cv2
import numpy as np
import time

# 確認したいカメラ
CAMERA_INDEX = 1

# ここを変えて1つずつ試す
# "DSHOW" / "MSMF" / "DEFAULT"
BACKEND_NAME = "DSHOW"

CAPTURE_W = 640
CAPTURE_H = 480
FPS = 15


def get_backend(backend_name):
    if backend_name == "DSHOW":
        return cv2.CAP_DSHOW
    if backend_name == "MSMF":
        return cv2.CAP_MSMF
    if backend_name == "DEFAULT":
        return None
    raise ValueError("BACKEND_NAME must be DSHOW, MSMF, or DEFAULT")


def open_camera(index, backend_name):
    backend = get_backend(backend_name)

    if backend is None:
        cap = cv2.VideoCapture(index)
    else:
        cap = cv2.VideoCapture(index, backend)

    if not cap.isOpened():
        raise RuntimeError(f"Camera index {index} を開けませんでした。backend={backend_name}")

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_H)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    return cap


def brightness(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray))


cap = open_camera(CAMERA_INDEX, BACKEND_NAME)

print("======================================")
print("Single Camera Backend Check")
print(f"CAMERA_INDEX = {CAMERA_INDEX}")
print(f"BACKEND_NAME = {BACKEND_NAME}")
print("q / Esc : 終了")
print("======================================")

# ウォームアップ
for _ in range(30):
    cap.read()
    time.sleep(0.01)

while True:
    ret, frame = cap.read()

    if not ret or frame is None:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(
            frame,
            "FRAME ERROR",
            (130, 240),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (0, 0, 255),
            3
        )
        b = 0.0
    else:
        b = brightness(frame)

    cv2.rectangle(frame, (0, 0), (640, 55), (0, 0, 0), -1)
    cv2.putText(
        frame,
        f"Index {CAMERA_INDEX} | {BACKEND_NAME} | brightness={b:.1f}",
        (10, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 255),
        2
    )

    cv2.imshow("Single Camera Backend Check", frame)

    key = cv2.waitKey(1) & 0xFF

    if key == ord("q") or key == 27:
        break

cap.release()
cv2.destroyAllWindows()
print("終了しました。")