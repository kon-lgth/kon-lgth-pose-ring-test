import cv2
import numpy as np
import socket
import json
import time
import os
import glob
import threading
from flask import Flask, Response

# ============================================================
# PoseRing B Set UDP Sender + Video Server
#
# サブPC用：
# Bセットカメラ2台で赤・黄・青・緑の3D座標を計算し、
# UDPでメインPCへ送信する。
#
# 追加機能：
# 同じカメラ映像をMJPEGでWeb配信する。
# これにより、sub_bset_video_server.py を別起動しなくても、
# mainPCのoperator画面でB CAM 0 / B CAM 1を確認できる。
#
# 重要：
# カメラを開くのはこのプログラム1つだけ。
# UDP送信用と映像配信用でカメラを二重に開かない。
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
# mainPCのIPv4アドレス。
# mainPCのモバイルホットスポットを使う場合、通常は 192.168.137.1。
# 必要に応じてPowerShell側で以下のように上書き可能：
#   $env:POSERING_MAIN_PC_IP="192.168.137.1"
MAIN_PC_IP = os.getenv("POSERING_MAIN_PC_IP", "192.168.137.1")
UDP_PORT = int(os.getenv("POSERING_UDP_PORT", "5005"))

# =========================
# Bセット設定
# =========================
CALIB_FILE = get_latest_calibration_file("calib_B_20")

# subPC側で正しく映ったBカメラ番号に合わせる
CAM0_INDEX = int(os.getenv("POSERING_B_CAM0", "0"))
CAM1_INDEX = int(os.getenv("POSERING_B_CAM1", "2"))

BACKEND = os.getenv("POSERING_B_BACKEND", "DSHOW")

CAPTURE_W = 640
CAPTURE_H = 480
FPS = 15

DISPLAY_MIRROR = True
VIEW_W = 640
VIEW_H = 480

SEND_INTERVAL_SEC = 0.05  # 約20Hz上限

# 色領域の最小面積
MIN_AREA = 40

MIN_AREA_BY_COLOR = {
    "RED": 300,
    "YELLOW": 500,
    "BLUE": 300,
    "GREEN": 500,
}

kernel = np.ones((5, 5), np.uint8)

# =========================
# Bカメラ映像配信設定
# =========================
ENABLE_VIDEO_SERVER = True
VIDEO_HOST = "0.0.0.0"
VIDEO_PORT = int(os.getenv("POSERING_SUB_VIDEO_PORT", "5010"))
JPEG_QUALITY = 70

app = Flask(__name__)
video_lock = threading.Lock()
latest_video_frames = {
    "b_cam0": None,
    "b_cam1": None,
}


# =========================
# HSV設定
# =========================
# 赤：はっきりした赤だけ拾う。背景誤検知を減らすためかなり厳しめ
LOWER_RED_1 = np.array([0, 190, 110])
UPPER_RED_1 = np.array([7, 255, 255])
LOWER_RED_2 = np.array([174, 190, 110])
UPPER_RED_2 = np.array([179, 255, 255])

# 黄色：はっきりした黄色だけ拾う。肌色・床・照明を拾いにくくする
LOWER_YELLOW = np.array([24, 170, 150])
UPPER_YELLOW = np.array([32, 255, 255])

# 青：背景は拾っていないので、少しだけ検知しやすくする
LOWER_BLUE = np.array([85, 60, 30])
UPPER_BLUE = np.array([140, 255, 255])

# 緑：濃い緑対象物向け
# 背景を避けるためH範囲を少し絞るが、濃い緑は暗いのでV下限は低めにする
LOWER_GREEN = np.array([45, 70, 25])
UPPER_GREEN = np.array([85, 255, 180])

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
        time.sleep(0.02)

    return cap


def maybe_flip_for_display(img):
    if DISPLAY_MIRROR:
        return cv2.flip(img, 1)
    return img


def resize_view(img):
    return cv2.resize(img, (VIEW_W, VIEW_H))


def update_video_frame(name, frame):
    """MJPEG配信用に最新フレームを保存する。"""
    if frame is None:
        return

    with video_lock:
        latest_video_frames[name] = frame.copy()


def get_jpeg_frame(name):
    with video_lock:
        frame = latest_video_frames.get(name)
        if frame is None:
            return None
        frame = frame.copy()

    ok, buffer = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
    )

    if not ok:
        return None

    return buffer.tobytes()


def mjpeg_generator(name):
    while True:
        jpeg = get_jpeg_frame(name)

        if jpeg is None:
            time.sleep(0.1)
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + jpeg
            + b"\r\n"
        )

        time.sleep(1.0 / FPS)


@app.route("/")
def video_index():
    return """
    <html>
      <head>
        <title>PoseRing B Camera UDP + Video</title>
      </head>
      <body style="font-family: sans-serif; background:#111; color:#eee;">
        <h1>PoseRing B Camera UDP + Video</h1>
        <p>This server sends B-set 3D data by UDP and streams B camera images.</p>
        <p><a href="/b_cam0" style="color:#8cf;">Open B CAM 0 only</a></p>
        <p><a href="/b_cam1" style="color:#8cf;">Open B CAM 1 only</a></p>
        <div style="display:flex; gap:16px; flex-wrap:wrap;">
          <div>
            <h2>B CAM 0</h2>
            <img src="/b_cam0" width="480">
          </div>
          <div>
            <h2>B CAM 1</h2>
            <img src="/b_cam1" width="480">
          </div>
        </div>
      </body>
    </html>
    """


@app.route("/b_cam0")
def b_cam0():
    return Response(
        mjpeg_generator("b_cam0"),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/b_cam1")
def b_cam1():
    return Response(
        mjpeg_generator("b_cam1"),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


def start_video_server_in_background():
    """Flask映像配信サーバーを別スレッドで起動する。"""
    if not ENABLE_VIDEO_SERVER:
        return None

    def run_server():
        app.run(
            host=VIDEO_HOST,
            port=VIDEO_PORT,
            debug=False,
            threaded=True,
            use_reloader=False,
        )

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()

    print("======================================")
    print("B Camera Video Server started")
    print(f"Open on subPC : http://localhost:{VIDEO_PORT}/")
    print(f"Open on mainPC: http://<SUB_PC_IP>:{VIDEO_PORT}/")
    print(f"B CAM 0       : http://<SUB_PC_IP>:{VIDEO_PORT}/b_cam0")
    print(f"B CAM 1       : http://<SUB_PC_IP>:{VIDEO_PORT}/b_cam1")
    print("======================================")

    return thread


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

    min_area = MIN_AREA_BY_COLOR.get(color_name, MIN_AREA)

    if area < min_area:
        return None, f"{color_name}: small area={int(area)} < {min_area}", (0, 0, 255)

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
    print("PoseRing B Set UDP Sender + Video Server")
    print(f"MAIN_PC_IP : {MAIN_PC_IP}")
    print(f"UDP_PORT   : {UDP_PORT}")
    print(f"VIDEO_PORT : {VIDEO_PORT}")
    print(f"CALIB_FILE : {CALIB_FILE}")
    print(f"CAMERAS    : {CAM0_INDEX}, {CAM1_INDEX}")
    print("q / Esc    : quit")
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

    # カメラを開いた後に、同じフレームを使って映像配信する。
    # ここではカメラを二重に開かない。
    start_video_server_in_background()

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

            # operator画面で見る映像は、この処理済み表示フレームを使う。
            # そのため、矩形・中心点・検出メッセージもブラウザ側で確認できる。
            update_video_frame("b_cam0", disp0)
            update_video_frame("b_cam1", disp1)

            display = np.hstack((resize_view(disp0), resize_view(disp1)))
            cv2.imshow("Sub PC B Set UDP Sender + Video", display)

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
