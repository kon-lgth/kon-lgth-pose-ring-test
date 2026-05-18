import cv2
import numpy as np
import time

# =========================
# Bセット用 設定
# =========================
CALIB_FILE = r"calibration_images\calib_B_20260504_140722\stereo_calibration_result.npz"

CAM0_INDEX = 4
CAM1_INDEX = 5

DISPLAY_MIRROR = True
SHOW_MASK = False

MIN_AREA = 70

kernel = np.ones((5, 5), np.uint8)

# =========================
# HSV設定
# 必要に応じて調整
# =========================
LOWER_RED_1 = np.array([0, 90, 50])
UPPER_RED_1 = np.array([10, 255, 255])
LOWER_RED_2 = np.array([170, 90, 50])
UPPER_RED_2 = np.array([179, 255, 255])

LOWER_YELLOW = np.array([20, 50, 80])
UPPER_YELLOW = np.array([35, 255, 255])

LOWER_BLUE = np.array([95, 70, 50])
UPPER_BLUE = np.array([130, 255, 255])

LOWER_GREEN = np.array([40, 60, 50])
UPPER_GREEN = np.array([85, 255, 255])

COLOR_ORDER = ["RED", "YELLOW", "BLUE", "GREEN"]

COLOR_CONFIGS = {
    "RED": {
        "box_color": (0, 0, 255),
        "center_color": (0, 255, 0),
        "text_color": (0, 0, 255),
    },
    "YELLOW": {
        "box_color": (0, 255, 255),
        "center_color": (255, 0, 255),
        "text_color": (0, 255, 255),
    },
    "BLUE": {
        "box_color": (255, 0, 0),
        "center_color": (0, 255, 255),
        "text_color": (255, 120, 0),
    },
    "GREEN": {
        "box_color": (0, 255, 0),
        "center_color": (0, 0, 255),
        "text_color": (0, 255, 0),
    },
}


# =========================
# マスク作成
# =========================
def make_red_mask(hsv):
    mask1 = cv2.inRange(hsv, LOWER_RED_1, UPPER_RED_1)
    mask2 = cv2.inRange(hsv, LOWER_RED_2, UPPER_RED_2)
    return cv2.bitwise_or(mask1, mask2)


def make_yellow_mask(hsv):
    return cv2.inRange(hsv, LOWER_YELLOW, UPPER_YELLOW)


def make_blue_mask(hsv):
    return cv2.inRange(hsv, LOWER_BLUE, UPPER_BLUE)


def make_green_mask(hsv):
    return cv2.inRange(hsv, LOWER_GREEN, UPPER_GREEN)


MASK_FUNCS = {
    "RED": make_red_mask,
    "YELLOW": make_yellow_mask,
    "BLUE": make_blue_mask,
    "GREEN": make_green_mask,
}


# =========================
# 関数
# =========================
def open_camera(index):
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)

    if not cap.isOpened():
        raise RuntimeError(f"カメラ index={index} を開けませんでした。")

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 15)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    return cap


def detect_color_center(source_frame, draw_frame, color_name):
    cfg = COLOR_CONFIGS[color_name]
    mask_func = MASK_FUNCS[color_name]

    hsv = cv2.cvtColor(source_frame, cv2.COLOR_BGR2HSV)

    mask = mask_func(hsv)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return mask, None, f"{color_name}: not found", (0, 0, 255)

    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)

    if area < MIN_AREA:
        return mask, None, f"{color_name}: too small area={int(area)}", (0, 0, 255)

    M = cv2.moments(c)

    if M["m00"] == 0:
        return mask, None, f"{color_name}: invalid moment", (0, 0, 255)

    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])

    x, y, w, h = cv2.boundingRect(c)

    cv2.rectangle(draw_frame, (x, y), (x + w, y + h), cfg["box_color"], 2)
    cv2.circle(draw_frame, (cx, cy), 6, cfg["center_color"], -1)

    return mask, (cx, cy, int(area)), f"{color_name}: ({cx}, {cy}) area={int(area)}", (255, 255, 255)


def triangulate_3d(cx0, cy0, cx1, cy1, P0, P1):
    pt0 = np.array([[cx0], [cy0]], dtype=np.float64)
    pt1 = np.array([[cx1], [cy1]], dtype=np.float64)

    pts_4d = cv2.triangulatePoints(P0, P1, pt0, pt1)
    pts_3d = pts_4d[:3] / pts_4d[3]

    return pts_3d.flatten()


def get_marker_3d(res0, res1, P0, P1):
    if res0 is None or res1 is None:
        return None

    cx0, cy0, area0 = res0
    cx1, cy1, area1 = res1

    point_3d = triangulate_3d(cx0, cy0, cx1, cy1, P0, P1)

    return {
        "point_3d": point_3d,
        "cx0": cx0,
        "cy0": cy0,
        "area0": area0,
        "cx1": cx1,
        "cy1": cy1,
        "area1": area1,
        "disparity": float(cx0 - cx1),
        "y_diff": abs(cy0 - cy1),
    }


def draw_horizontal_guides(img, step=40):
    out = img.copy()
    h, w = out.shape[:2]

    for y in range(step, h, step):
        cv2.line(out, (0, y), (w - 1, y), (255, 0, 0), 1)

    return out


def maybe_flip_for_display(img):
    if DISPLAY_MIRROR:
        return cv2.flip(img, 1)
    return img


def format_vec(v):
    if v is None:
        return "---"
    return f"X:{v[0]:.1f}  Y:{v[1]:.1f}  Z:{v[2]:.1f}"


# =========================
# キャリブレーション読み込み
# =========================
data = np.load(CALIB_FILE)

map0x = data["map0x"]
map0y = data["map0y"]
map1x = data["map1x"]
map1y = data["map1y"]

P0 = data["P0"]
P1 = data["P1"]

# =========================
# カメラ開始
# =========================
cap0 = open_camera(CAM0_INDEX)
cap1 = open_camera(CAM1_INDEX)

print("======================================")
print("B SET Four Color 3D Check")
print(f"CALIB_FILE: {CALIB_FILE}")
print(f"CAM0_INDEX: {CAM0_INDEX}")
print(f"CAM1_INDEX: {CAM1_INDEX}")
print("q / Esc : 終了")
print("======================================")

last_points = {name: None for name in COLOR_ORDER}
last_source = {name: "NO DATA" for name in COLOR_ORDER}

while True:
    ret0, frame0 = cap0.read()
    ret1, frame1 = cap1.read()

    if not ret0 or frame0 is None:
        print("B Cam0 のフレーム取得に失敗しました。")
        break

    if not ret1 or frame1 is None:
        print("B Cam1 のフレーム取得に失敗しました。")
        break

    # rectification
    rect0 = cv2.remap(frame0, map0x, map0y, cv2.INTER_LINEAR)
    rect1 = cv2.remap(frame1, map1x, map1y, cv2.INTER_LINEAR)

    out0 = draw_horizontal_guides(rect0)
    out1 = draw_horizontal_guides(rect1)

    results = {}
    masks = {}

    for name in COLOR_ORDER:
        mask0, res0, msg0, color0 = detect_color_center(rect0, out0, name)
        mask1, res1, msg1, color1 = detect_color_center(rect1, out1, name)

        data_3d = get_marker_3d(res0, res1, P0, P1)

        if data_3d is not None:
            point = data_3d["point_3d"]
            last_points[name] = point.copy()
            last_source[name] = "LIVE"

            results[name] = {
                "point": point,
                "source": "LIVE",
                "y_diff": data_3d["y_diff"],
                "msg0": msg0,
                "msg1": msg1,
                "color0": color0,
                "color1": color1,
            }

            cfg = COLOR_CONFIGS[name]
            cv2.line(out0, (0, data_3d["cy0"]), (out0.shape[1] - 1, data_3d["cy0"]), cfg["box_color"], 1)
            cv2.line(out1, (0, data_3d["cy1"]), (out1.shape[1] - 1, data_3d["cy1"]), cfg["box_color"], 1)

        else:
            if last_points[name] is not None:
                results[name] = {
                    "point": last_points[name],
                    "source": "LAST",
                    "y_diff": None,
                    "msg0": msg0,
                    "msg1": msg1,
                    "color0": color0,
                    "color1": color1,
                }
                last_source[name] = "LAST"
            else:
                results[name] = {
                    "point": None,
                    "source": "NO DATA",
                    "y_diff": None,
                    "msg0": msg0,
                    "msg1": msg1,
                    "color0": color0,
                    "color1": color1,
                }

        masks[name] = (mask0, mask1)

    # =========================
    # 情報表示
    # =========================
    info = np.zeros((250, out0.shape[1] * 2, 3), dtype=np.uint8)

    cv2.putText(
        info,
        "B SET Four Color 3D Check",
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        (255, 255, 255),
        2
    )

    cv2.putText(
        info,
        "Check whether RED / YELLOW / BLUE / GREEN can get 3D coordinates in B set",
        (20, 70),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        2
    )

    y = 110

    for name in COLOR_ORDER:
        r = results[name]
        cfg = COLOR_CONFIGS[name]

        point_text = format_vec(r["point"])
        ydiff_text = "---" if r["y_diff"] is None else f"{r['y_diff']:.2f}px"

        text = f"{name:6s} | {r['source']:7s} | {point_text} | y_diff:{ydiff_text}"

        if r["source"] == "LIVE":
            text_color = (0, 255, 0)
        elif r["source"] == "LAST":
            text_color = (0, 255, 255)
        else:
            text_color = (0, 0, 255)

        cv2.putText(
            info,
            text,
            (20, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            text_color,
            2
        )

        y += 32

    # 表示用反転
    disp0 = maybe_flip_for_display(out0)
    disp1 = maybe_flip_for_display(out1)

    # 文字は反転後に描画
    text_y = 28
    for name in COLOR_ORDER:
        r = results[name]

        cv2.putText(
            disp0,
            r["msg0"],
            (10, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            r["color0"],
            2
        )

        cv2.putText(
            disp1,
            r["msg1"],
            (10, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            r["color1"],
            2
        )

        text_y += 26

    cv2.putText(
        disp0,
        f"B Cam0 Index {CAM0_INDEX}",
        (20, disp0.shape[0] - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (0, 255, 255),
        2
    )

    cv2.putText(
        disp1,
        f"B Cam1 Index {CAM1_INDEX}",
        (20, disp1.shape[0] - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (0, 255, 255),
        2
    )

    top = np.hstack((disp0, disp1))
    display = np.vstack((top, info))

    cv2.imshow("B SET Four Color 3D Check", display)

    if SHOW_MASK:
        mask_rows = []

        for name in COLOR_ORDER:
            m0, m1 = masks[name]
            m0_bgr = cv2.cvtColor(m0, cv2.COLOR_GRAY2BGR)
            m1_bgr = cv2.cvtColor(m1, cv2.COLOR_GRAY2BGR)

            mask_rows.append(
                np.hstack(
                    (
                        maybe_flip_for_display(m0_bgr),
                        maybe_flip_for_display(m1_bgr)
                    )
                )
            )

        cv2.imshow("B SET Masks", np.vstack(mask_rows))

    key = cv2.waitKey(1) & 0xFF

    if key == ord("q") or key == 27:
        break

cap0.release()
cap1.release()
cv2.destroyAllWindows()

print("終了しました。")