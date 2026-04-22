import cv2
import numpy as np

# 緑検出範囲
lower_green = np.array([35, 60, 80])
upper_green = np.array([85, 255, 255])

kernel = np.ones((5, 5), np.uint8)

def detect_green(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower_green, upper_green)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    result = None
    text = "GREEN: not found"

    if contours:
        c = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(c)

        if area > 500:
            x, y, w, h = cv2.boundingRect(c)
            cx = x + w // 2
            cy = y + h // 2

            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.circle(frame, (cx, cy), 6, (0, 0, 255), -1)

            text = f"GREEN: center=({cx}, {cy}) area={int(area)}"
            result = (cx, cy, int(area))

    cv2.putText(frame, text, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (255, 255, 255), 2)

    return frame, result


cap0 = cv2.VideoCapture(0)  # PCカメラ
cap1 = cv2.VideoCapture(1)  # iPhone (DroidCam)

if not cap0.isOpened():
    raise RuntimeError("カメラ0を開けませんでした")

if not cap1.isOpened():
    raise RuntimeError("カメラ1を開けませんでした")

for cap in [cap0, cap1]:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

while True:
    ret0, frame0 = cap0.read()
    ret1, frame1 = cap1.read()

    if not ret0 or not ret1:
        print("フレーム取得失敗")
        break

    frame0 = cv2.flip(frame0, 1)
    frame1 = cv2.flip(frame1, 1)

    out0, res0 = detect_green(frame0)
    out1, res1 = detect_green(frame1)

    # 下に両カメラの座標情報をまとめて表示する黒い画像
    info = np.zeros((140, 1280, 3), dtype=np.uint8)

    if res0 is not None:
        cx0, cy0, area0 = res0
        text0 = f"Camera 0 (PC): x={cx0}, y={cy0}, area={area0}"
    else:
        text0 = "Camera 0 (PC): not found"

    if res1 is not None:
        cx1, cy1, area1 = res1
        text1 = f"Camera 1 (iPhone): x={cx1}, y={cy1}, area={area1}"
    else:
        text1 = "Camera 1 (iPhone): not found"

    cv2.putText(info, text0, (20, 45),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                (0, 255, 0), 2)

    cv2.putText(info, text1, (20, 95),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                (0, 255, 255), 2)

    # 2画面を横につなぐ
    combined = np.hstack((out0, out1))
    display = np.vstack((combined, info))

    cv2.imshow("2 Camera Green Tracking", display)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q") or key == 27:
        break

cap0.release()
cap1.release()
cv2.destroyAllWindows()