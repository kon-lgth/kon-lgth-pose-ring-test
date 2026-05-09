import cv2
import numpy as np
import socket
import json
import time
import os
import glob

# ============================================================
# PoseRing B Set UDP Sender
#
# サブPC用：
# Bセットカメラ2台で赤・黄・青・緑の3D座標を計算し、
# UDPでメインPCへ送信する。
# ============================================================

def get_latest_calibration_file(prefix="calib_B_20"):
    """
    calibration_images 内から、指定prefixで始まるフォルダのうち、
    stereo_calibration_result.npz が存在する最新フォルダを自動で選ぶ。
    """
    base_dir = "calibration_images"

    pattern = os.path.join(base_dir, prefix + "*", "stereo_calibration_result.npz")
    files = glob.glob(pattern)

    if not files:
        raise FileNotFoundError(
            f"キャリブレーションファイルが見つかりません: {pattern}"
        )

    latest_file = max(files, key=os.path.getmtime)

    print("======================================")
    print("[AUTO CALIB] 最新のBセットキャリブレーションを使用します")
    print(f"[AUTO CALIB] prefix: {prefix}")
    print(f"[AUTO CALIB] file  : {latest_file}")
    print("======================================")

    return latest_file
    
# =========================
# UDP送信設定
# =========================
# メインPCのIPv4アドレスに変更する
MAIN_PC_IP = "10.128.26.47"
UDP_PORT = 5005

# =========================
# Bセット設定
# =========================
CALIB_FILE = get_latest_calibration_file("calib_B_20")

CAM0_INDEX = 1
CAM1_INDEX = 2

BACKEND = "DSHOW"

CAPTURE_W = 640
CAPTURE_H = 480
FPS = 15

DISPLAY_MIRROR = True
VIEW_W = 320
VIEW_H = 240

SEND_INTERVAL_SEC = 0.05  # 約20Hz上限

# 色領域の最小面積
MIN_AREA = 40
kernel = np.ones((5, 5), np.uint8)

# =========================
# HSV設定
# =========================
LOWER_RED_1 = np.array([0, 120, 50])
UPPER_RED_1 = np.array([10, 255, 255])
LOWER_RED_2 = np.array([170, 120, 50])
UPPER_RED_2 = np.array([179, 255, 255])

LOWER_YELLOW = np.array([20, 80, 80])
UPPER_YELLOW = np.array([35, 255, 255])

LOWER_BLUE = np.array([95, 150, 50])
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


def open_camera(index):
    if BACKEND == "DSHOW":
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(index)

    if not cap.isOpened():
        raise RuntimeError(f"カメラ index={index} を開けませんでした。")

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_H)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    for _ in range(10):
        cap.read()

    return cap


def maybe_flip_for_display(img):
    if DISPLAY_MIRROR:
        return cv2.flip(img, 1)
    return img


def resize_view(img):
    return cv2.resize(img, (VIEW_W, VIEW_H))


def detect_color_center(source_frame, draw_frame, color_name):
    cfg = COLOR_CONFIGS[color_name]
    mask_func = MASK_FUNCS[color_name]

    hsv = cv2.cvtColor(source_frame, cv2.COLOR_BGR2HSV)
    mask = mask_func(hsv)

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None, f"{color_name}: not found", (0, 0, 255)

    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)

    if area < MIN_AREA:
        return None, f"{color_name}: small area={int(area)}", (0, 0, 255)

    M = cv2.moments(c)
    if M["m00"] == 0:
        return None, f"{color_name}: invalid moment", (0, 0, 255)

    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])

    x, y, w, h = cv2.boundingRect(c)
    cv2.rectangle(draw_frame, (x, y), (x + w, y + h), cfg["box_color"], 2)
    cv2.circle(draw_frame, (cx, cy), 6, cfg["center_color"], -1)

    return (cx, cy, int(area)), f"{color_name}: ({cx},{cy}) area={int(area)}", (255, 255, 255)


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
        "point": [float(point_3d[0]), float(point_3d[1]), float(point_3d[2])],
        "cx0": int(cx0),
        "cy0": int(cy0),
        "area0": int(area0),
        "cx1": int(cx1),
        "cy1": int(cy1),
        "area1": int(area1),
        "disparity": float(cx0 - cx1),
        "y_diff": float(abs(cy0 - cy1)),
    }


def main():
    print("======================================")
    print("PoseRing B Set UDP Sender")
    print(f"MAIN_PC_IP: {MAIN_PC_IP}")
    print(f"UDP_PORT  : {UDP_PORT}")
    print(f"CALIB_FILE: {CALIB_FILE}")
    print(f"CAMERAS   : {CAM0_INDEX}, {CAM1_INDEX}")
    print("q / Esc   : quit")
    print("======================================")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    data = np.load(CALIB_FILE)
    map0x = data["map0x"]
    map0y = data["map0y"]
    map1x = data["map1x"]
    map1y = data["map1y"]
    P0 = data["P0"]
    P1 = data["P1"]

    cap0 = open_camera(CAM0_INDEX)
    cap1 = open_camera(CAM1_INDEX)

    frame_count = 0
    last_send_time = 0.0

    try:
        while True:
            ret0, frame0 = cap0.read()
            ret1, frame1 = cap1.read()

            if not ret0 or frame0 is None:
                raise RuntimeError(f"Cam0 index={CAM0_INDEX} のフレーム取得に失敗しました。")
            if not ret1 or frame1 is None:
                raise RuntimeError(f"Cam1 index={CAM1_INDEX} のフレーム取得に失敗しました。")

            rect0 = cv2.remap(frame0, map0x, map0y, cv2.INTER_LINEAR)
            rect1 = cv2.remap(frame1, map1x, map1y, cv2.INTER_LINEAR)

            out0 = rect0.copy()
            out1 = rect1.copy()

            colors_payload = {}

            y_text = 30

            for color in COLOR_ORDER:
                res0, msg0, msg_color0 = detect_color_center(rect0, out0, color)
                res1, msg1, msg_color1 = detect_color_center(rect1, out1, color)

                marker_3d = get_marker_3d(res0, res1, P0, P1)

                if marker_3d is not None:
                    colors_payload[color] = {
                        "live": True,
                        "point": marker_3d["point"],
                        "y_diff": marker_3d["y_diff"],
                        "disparity": marker_3d["disparity"],
                    }

                    cfg = COLOR_CONFIGS[color]
                    cv2.line(out0, (0, marker_3d["cy0"]), (out0.shape[1] - 1, marker_3d["cy0"]), cfg["box_color"], 1)
                    cv2.line(out1, (0, marker_3d["cy1"]), (out1.shape[1] - 1, marker_3d["cy1"]), cfg["box_color"], 1)
                else:
                    colors_payload[color] = {
                        "live": False,
                        "point": None,
                        "y_diff": None,
                        "disparity": None,
                    }

                cv2.putText(out0, msg0, (10, y_text), cv2.FONT_HERSHEY_SIMPLEX, 0.5, msg_color0, 1)
                cv2.putText(out1, msg1, (10, y_text), cv2.FONT_HERSHEY_SIMPLEX, 0.5, msg_color1, 1)
                y_text += 24

            now = time.time()

            if now - last_send_time >= SEND_INTERVAL_SEC:
                payload = {
                    "type": "bset_3d",
                    "from": "sub_pc_bset",
                    "frame": frame_count,
                    "time": now,
                    "colors": colors_payload,
                }

                message = json.dumps(payload).encode("utf-8")
                sock.sendto(message, (MAIN_PC_IP, UDP_PORT))

                live_colors = [c for c in COLOR_ORDER if colors_payload[c]["live"]]
                print(f"sent frame={frame_count} live={live_colors}")

                last_send_time = now
                frame_count += 1

            disp0 = maybe_flip_for_display(out0)
            disp1 = maybe_flip_for_display(out1)

            cv2.putText(disp0, f"B Cam0 Index {CAM0_INDEX}", (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.putText(disp1, f"B Cam1 Index {CAM1_INDEX}", (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

            display = np.hstack((resize_view(disp0), resize_view(disp1)))
            cv2.imshow("Sub PC B Set UDP Sender", display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:
                break

    finally:
        cap0.release()
        cap1.release()
        cv2.destroyAllWindows()
        print("終了しました。")


if __name__ == "__main__":
    main()
