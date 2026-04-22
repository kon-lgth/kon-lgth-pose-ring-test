import cv2
import numpy as np

# カメラを開く（最初のカメラ）
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    raise RuntimeError("カメラを開けませんでした。別のアプリが使っていないか確認してください。")

# 画面サイズ
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

# 追跡する色：緑（HSV）
lower_green = np.array([35, 80, 80])
upper_green = np.array([85, 255, 255])

# ノイズ除去用
kernel = np.ones((5, 5), np.uint8)

while True:
    ret, frame = cap.read()
    if not ret:
        print("フレームを取得できませんでした。")
        break

    # 左右反転
    frame = cv2.flip(frame, 1)

    # BGR -> HSV
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # 緑色だけを抽出
    mask = cv2.inRange(hsv, lower_green, upper_green)

    # ノイズを減らす
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    # 輪郭を探す
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    text = "green not found"

    if contours:
        # 一番大きい輪郭を使う
        c = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(c)

        if area > 500:
            x, y, w, h = cv2.boundingRect(c)
            cx = x + w // 2
            cy = y + h // 2

            # 枠と中心点を表示
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.circle(frame, (cx, cy), 6, (0, 0, 255), -1)

            text = f"center=({cx}, {cy})  area={int(area)}"

    cv2.putText(
        frame,
        text,
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2
    )

    cv2.imshow("Camera", frame)
    cv2.imshow("Mask", mask)

    # q または Esc で終了
    key = cv2.waitKey(1) & 0xFF
    if key == ord("q") or key == 27:
        break

cap.release()
cv2.destroyAllWindows()