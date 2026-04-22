import cv2
import numpy as np

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    raise RuntimeError("カメラを開けませんでした。別のアプリが使っていないか確認してください。")

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

kernel = np.ones((5, 5), np.uint8)

def get_largest_color_region(mask, min_area=500):
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None

    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)

    if area < min_area:
        return None

    x, y, w, h = cv2.boundingRect(c)
    cx = x + w // 2
    cy = y + h // 2

    return {
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "cx": cx,
        "cy": cy,
        "area": int(area)
    }

while True:
    ret, frame = cap.read()
    if not ret:
        print("フレームを取得できませんでした。")
        break

    frame = cv2.flip(frame, 1)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # 色の範囲（HSV）
    # 赤は 0 付近と 180 付近に分かれるので2つ必要
    red_mask1 = cv2.inRange(hsv, np.array([0, 120, 80]), np.array([10, 255, 255]))
    red_mask2 = cv2.inRange(hsv, np.array([170, 120, 80]), np.array([180, 255, 255]))
    red_mask = cv2.bitwise_or(red_mask1, red_mask2)

    green_mask = cv2.inRange(hsv, np.array([35, 80, 80]), np.array([85, 255, 255]))
    blue_mask = cv2.inRange(hsv, np.array([100, 120, 80]), np.array([130, 255, 255]))
    yellow_mask = cv2.inRange(hsv, np.array([15, 80, 80]), np.array([40, 255, 255]))

    color_data = [
        ("RED", red_mask, (0, 0, 255)),
        ("GREEN", green_mask, (0, 255, 0)),
        ("BLUE", blue_mask, (255, 0, 0)),
        ("YELLOW", yellow_mask, (0, 255, 255)),
    ]

    y_text = 30

    # 4色のマスクをまとめて表示するための画像
    combined_mask = cv2.bitwise_or(red_mask, green_mask)
    combined_mask = cv2.bitwise_or(combined_mask, blue_mask)
    combined_mask = cv2.bitwise_or(combined_mask, yellow_mask)

    for name, mask, box_color in color_data:
        result = get_largest_color_region(mask)

        if result is not None:
            x = result["x"]
            y = result["y"]
            w = result["w"]
            h = result["h"]
            cx = result["cx"]
            cy = result["cy"]
            area = result["area"]

            cv2.rectangle(frame, (x, y), (x + w, y + h), box_color, 2)
            cv2.circle(frame, (cx, cy), 6, (255, 255, 255), -1)

            text = f"{name}: center=({cx}, {cy}) area={area}"
        else:
            text = f"{name}: not found"

        cv2.putText(
            frame,
            text,
            (10, y_text),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            box_color,
            2
        )
        y_text += 30

    cv2.imshow("Camera", frame)
    cv2.imshow("Combined Mask", combined_mask)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q") or key == 27:
        break

cap.release()
cv2.destroyAllWindows()