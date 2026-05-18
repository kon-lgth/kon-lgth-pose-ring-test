import cv2
import numpy as np
import time

import socket
import json

import os
import glob

import asyncio
import threading
import queue
from bleak import BleakScanner, BleakClient

# ============================================================
# PoseRing 2PC Main
#
# メインPC:
#   Aセットカメラ2台を直接読む
#   サブPCからBセット3D座標をUDPで受信する
#   Aで見えている色はAで判定
#   Aで見失った色はB_REMOTEで補助
#   XIAOへBLE送信する
#
# サブPC:
#   Bセットカメラ2台を読む
#   Bセット3D座標をUDP送信する
#
# 重要:
#   A/Bの3D座標系は直接混ぜない。
#   Aを使う色は A現在座標 vs A目標座標。
#   Bを使う色は B現在座標 vs B目標座標。
# ============================================================
def get_latest_calibration_file(prefix):
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
    print("[AUTO CALIB] 最新キャリブレーションを使用します")
    print(f"[AUTO CALIB] prefix: {prefix}")
    print(f"[AUTO CALIB] file  : {latest_file}")
    print("======================================")

    return latest_file
# =========================
# 設定
# =========================

# Aセット用キャリブレーション結果
A_CALIB_FILE = get_latest_calibration_file("calib_20")

# Bセット用キャリブレーション結果
# リモートBセットを使う場合、このファイルは基本的には使わない。
# USE_REMOTE_B_SET = False にした場合だけ使う。
B_CALIB_FILE = r"calibration_images\calib_B_20260504_140722\stereo_calibration_result.npz"

A_CAM0_INDEX = 1
A_CAM1_INDEX = 2

# ローカルBセットを使う場合だけ使う。
B_CAM0_INDEX = 4
B_CAM1_INDEX = 5

# Bセットを使うかどうか
USE_B_SET = True

# True:
#   サブPCからUDPで届くBセット座標を使う
# False:
#   メインPCに接続されたBカメラを直接使う
USE_REMOTE_B_SET = True

# サブPCからのBセット座標を受け取る設定
REMOTE_B_UDP_IP = "0.0.0.0"
REMOTE_B_UDP_PORT = 5005

# =========================
# XIAO BLE フィードバック設定
# =========================
ENABLE_XIAO_BLE = True

# デバイス側ArduinoコードのBLE名・Characteristic UUIDと一致させる
BLE_DEVICE_NAME = "PoseRing_YELLOW"
BLE_LED_CHAR_UUID = "19B10001-E8F2-537E-4F6C-D104768A1214"

# True : 対象色が今フレームでLIVE検出され、かつゴール内のときだけLED反応
# False: 一時的な見失い時のLAST_USED判定でもLED反応を維持する
REQUIRE_TARGET_LIVE_FOR_LED = False

# ステージ内外LED制御
# True : カメラ画面内でLIVE検出されている時だけ白/赤で点灯し、画面外では消灯する
# False: 従来に近い挙動。BLE接続中は基本白で待機する
ENABLE_STAGE_VISIBLE_LED = True

# True : ステージ内外判定ではLAST_USEDを使わず、A/BどちらかでLIVE検出できた時だけ「ステージ内」とする
# 画面外に出たらすぐ消灯させたいので、基本は True 推奨
STAGE_VISIBLE_REQUIRES_LIVE = True

# 対象色を一瞬見失っても、すぐにはステージ外扱いにしない猶予時間。
# 体による一瞬の遮蔽でLEDがチカチカ消えるのを防ぐ。
# ただし、この猶予時間を超えて見えなければステージ外扱いで消灯する。
STAGE_LOST_GRACE_SEC = 1.0

# BLEで反応させる判定対象の色
FEEDBACK_TARGET_COLOR = "RED"

# 距離に応じた赤LED輝度フィードバック設定
FEEDBACK_MIN_RED_BRIGHTNESS = 20
FEEDBACK_MAX_RED_BRIGHTNESS = 255

# 表示設定
DISPLAY_MIRROR = True
VIEW_W = 320
VIEW_H = 240

# 写真保存設定
# sキーで出題時写真、ALL CLEAR時にクリア時写真と比較画像を保存する。
ENABLE_PHOTO_CAPTURE = True
PHOTO_BASE_DIR = "pose_photos"
PHOTO_WINDOW_NAME = "PoseRing Result Photos"
PHOTO_RESULT_W = 640
PHOTO_RESULT_H = 480

# 結果写真ウィンドウ表示サイズ。小さめにしてモニターからはみ出さないようにする。
PHOTO_DISPLAY_MAX_W = 1200
PHOTO_DISPLAY_MAX_H = 650
COMPARISON_PANEL_W = 560
COMPARISON_PANEL_H = 500

# カメラ設定
CAPTURE_W = 640
CAPTURE_H = 480
FPS = 15

# カメラの開き方
A_BACKEND = "DEFAULT"
B_BACKEND = "DSHOW"

# 判定設定
CLEAR_DISTANCE_MM = 390.0
HOLD_TIME_SEC = 2.0

# CLEAR_DISTANCE_MM=390なら、1170mm以内から赤くなり始める
FEEDBACK_MAX_DISTANCE_MM = CLEAR_DISTANCE_MM * 3.0

# 色を見失った時、最後の判定情報を使い続ける最大時間
LOST_HOLD_SEC = 0.7

# 色領域の最小面積
MIN_AREA = 40

kernel = np.ones((5, 5), np.uint8)

# =========================
# HSV設定
# 照明や素材に合わせて調整する
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
# 基本関数
# =========================
def open_camera(index, backend_mode):
    """
    カメラごとに開き方を変える。
    """

    if backend_mode == "DSHOW":
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    elif backend_mode == "DEFAULT":
        cap = cv2.VideoCapture(index)
    else:
        raise ValueError("backend_mode must be 'DEFAULT' or 'DSHOW'")

    if not cap.isOpened():
        raise RuntimeError(f"カメラ index={index} を開けませんでした。backend={backend_mode}")

    if backend_mode == "DEFAULT":
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_H)

    if backend_mode == "DSHOW":
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_H)
        cap.set(cv2.CAP_PROP_FPS, FPS)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # ウォームアップ
    for _ in range(10):
        cap.read()

    return cap


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


def resize_view(img):
    return cv2.resize(img, (VIEW_W, VIEW_H))


def format_vec(v):
    if v is None:
        return "---"
    return f"X:{v[0]:.1f} Y:{v[1]:.1f} Z:{v[2]:.1f}"


def get_timestamp_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def get_timestamp_for_filename():
    return time.strftime("%Y%m%d_%H%M%S")


def create_photo_session_dir():
    session_dir = os.path.join(PHOTO_BASE_DIR, "session_" + get_timestamp_for_filename())
    os.makedirs(session_dir, exist_ok=True)
    return session_dir


def resize_with_aspect_padding(image, target_w, target_h, bg_color=(20, 20, 20)):
    """
    画像の縦横比を保ったまま target_w x target_h に収める。
    余った部分は bg_color で塗りつぶす。
    """
    if image is None:
        return None

    h, w = image.shape[:2]
    if w <= 0 or h <= 0:
        return None

    scale = min(target_w / w, target_h / h)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))

    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    canvas = np.full((target_h, target_w, 3), bg_color, dtype=np.uint8)

    x0 = (target_w - new_w) // 2
    y0 = (target_h - new_h) // 2
    canvas[y0:y0 + new_h, x0:x0 + new_w] = resized

    return canvas


def make_photo_from_a_set(set_a, title, subtitle=""):
    """
    AセットのA Cam0画像だけを使い、タイトル付きの保存用写真を作る。
    A Cam1は3D計測には使うが、出題時/クリア時の記録写真には使わない。
    """
    if set_a.out0 is None:
        return None

    image = maybe_flip_for_display(set_a.out0.copy())
    image = cv2.resize(image, (PHOTO_RESULT_W, PHOTO_RESULT_H))

    header_h = 90
    photo = np.full((image.shape[0] + header_h, image.shape[1], 3), 25, dtype=np.uint8)
    photo[header_h:, :] = image

    cv2.putText(
        photo,
        title,
        (25, 38),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (255, 255, 255),
        2,
    )
    cv2.putText(
        photo,
        f"{subtitle}  {get_timestamp_text()}",
        (25, 70),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (200, 200, 200),
        1,
    )

    cv2.putText(photo, "A Cam0", (25, header_h + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

    return photo


def save_photo_image(image, session_dir, filename):
    if image is None or session_dir is None:
        return None

    os.makedirs(session_dir, exist_ok=True)
    path = os.path.join(session_dir, filename)
    ok = cv2.imwrite(path, image)
    if ok:
        print(f"[PHOTO SAVED] {path}")
        return path

    print(f"[PHOTO SAVE FAILED] {path}")
    return None


def make_comparison_photo(challenge_image, clear_image, clear_time=None):
    """出題時写真とクリア時写真を左右に並べた比較画像を作る。

    A Cam0写真だけを使う。
    縦横比を保ったまま、比較用の小さめパネルに収めることで、
    画像の横伸びとモニターからのはみ出しを防ぐ。
    """
    if challenge_image is None or clear_image is None:
        return None

    single_w = COMPARISON_PANEL_W
    single_h = COMPARISON_PANEL_H

    left = resize_with_aspect_padding(challenge_image, single_w, single_h)
    right = resize_with_aspect_padding(clear_image, single_w, single_h)

    header_h = 75
    label_h = 38
    canvas_h = header_h + label_h + single_h
    canvas_w = single_w * 2
    canvas = np.full((canvas_h, canvas_w, 3), 20, dtype=np.uint8)

    title = "PoseRing Result"
    if clear_time is not None:
        title += f"  /  Clear Time: {clear_time:.2f} sec"

    cv2.putText(canvas, title, (25, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    cv2.putText(canvas, get_timestamp_text(), (25, 63), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (190, 190, 190), 1)

    cv2.putText(canvas, "CHALLENGE / TARGET POSE", (25, header_h + 27), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 255), 2)
    cv2.putText(canvas, "CLEAR POSE", (single_w + 25, header_h + 27), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 0), 2)

    y0 = header_h + label_h
    canvas[y0:y0 + single_h, 0:single_w] = left
    canvas[y0:y0 + single_h, single_w:single_w * 2] = right

    cv2.line(canvas, (single_w, header_h), (single_w, canvas_h - 1), (120, 120, 120), 2)
    return canvas


def show_photo_window_safely(image):
    """結果写真をモニターに収まるサイズで表示する。"""
    if image is None:
        return

    h, w = image.shape[:2]
    scale = min(PHOTO_DISPLAY_MAX_W / w, PHOTO_DISPLAY_MAX_H / h, 1.0)

    if scale < 1.0:
        display_image = cv2.resize(
            image,
            (int(w * scale), int(h * scale)),
            interpolation=cv2.INTER_AREA,
        )
    else:
        display_image = image

    cv2.imshow(PHOTO_WINDOW_NAME, display_image)


def close_photo_window_safely():
    try:
        cv2.destroyWindow(PHOTO_WINDOW_NAME)
    except Exception:
        pass


def detect_color_center(source_frame, draw_frame, color_name):
    """
    source_frameで色検出し、draw_frameに描画する。
    成功すれば (cx, cy, area) を返す。
    """
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
        return mask, None, f"{color_name}: small area={int(area)}", (0, 0, 255)

    M = cv2.moments(c)
    if M["m00"] == 0:
        return mask, None, f"{color_name}: invalid moment", (0, 0, 255)

    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])

    x, y, w, h = cv2.boundingRect(c)
    cv2.rectangle(draw_frame, (x, y), (x + w, y + h), cfg["box_color"], 2)
    cv2.circle(draw_frame, (cx, cy), 6, cfg["center_color"], -1)

    return mask, (cx, cy, int(area)), f"{color_name}: ({cx},{cy}) area={int(area)}", (255, 255, 255)


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


def judge_distance(current_3d, target_3d):
    if current_3d is None or target_3d is None:
        return None, False, "NO DATA", (0, 0, 255)

    distance = float(np.linalg.norm(current_3d - target_3d))

    if distance <= CLEAR_DISTANCE_MM:
        return distance, True, "OK", (0, 255, 0)
    if distance <= CLEAR_DISTANCE_MM * 2:
        return distance, False, "CLOSE", (0, 255, 255)
    return distance, False, "FAR", (0, 0, 255)


def distance_to_red_brightness(distance_mm):
    """
    距離を赤色LEDの輝度値(2-255)に変換する。
    - 距離が FEEDBACK_MAX_DISTANCE_MM 以上: None（白色待機）
    - 距離が 0 に近いほど明るい赤
    """
    if distance_mm is None:
        return None

    if distance_mm >= FEEDBACK_MAX_DISTANCE_MM:
        return None

    closeness = 1.0 - (float(distance_mm) / float(FEEDBACK_MAX_DISTANCE_MM))
    closeness = max(0.0, min(1.0, closeness))

    brightness = FEEDBACK_MIN_RED_BRIGHTNESS + closeness * (
        FEEDBACK_MAX_RED_BRIGHTNESS - FEEDBACK_MIN_RED_BRIGHTNESS
    )

    return int(round(brightness))


# =========================
# XIAO BLE LED / NeoPixel 制御
# =========================
class BleFeedbackController:
    """
    XIAO nRF52840 SenseへBLEで状態値/赤色輝度値を送るためのクラス。
    OpenCVのメインループを止めないように、BLE通信は別スレッドで行う。

    送信値:
      0       = OFF / 終了時・切断前
      1       = BLE接続中の待機表示（白色）
      2-255   = 赤色LEDの輝度値
    """

    STATE_OFF = 0
    STATE_CONNECTED_WHITE = 1
    MIN_RED_BRIGHTNESS_VALUE = 2

    def __init__(self, device_name, char_uuid, scan_timeout=8.0):
        self.device_name = device_name
        self.char_uuid = char_uuid
        self.scan_timeout = scan_timeout
        self.cmd_queue = queue.Queue(maxsize=1)
        self.stop_event = threading.Event()
        self.thread = None

        self.requested_value = self.STATE_CONNECTED_WHITE
        self.last_queued_value = None
        self.is_connected = False

    def start(self):
        self.thread = threading.Thread(target=self._thread_main, daemon=True)
        self.thread.start()

    def stop(self):
        self.set_state(self.STATE_OFF)
        time.sleep(0.2)

        self.stop_event.set()
        try:
            self.cmd_queue.put_nowait(None)
        except queue.Full:
            pass

        if self.thread is not None:
            self.thread.join(timeout=3.0)

    def set_state(self, state):
        value = int(np.clip(int(state), 0, 255))

        if value == self.last_queued_value:
            return

        self.requested_value = value
        self.last_queued_value = value

        try:
            while True:
                self.cmd_queue.get_nowait()
        except queue.Empty:
            pass

        try:
            self.cmd_queue.put_nowait(value)
            print(f"[BLE SEND REQUEST] {value}")
        except queue.Full:
            pass

    def set_red_brightness(self, brightness):
        if brightness is None or brightness <= 0:
            self.set_state(self.STATE_CONNECTED_WHITE)
        else:
            self.set_state(max(self.MIN_RED_BRIGHTNESS_VALUE, min(255, int(brightness))))

    def _thread_main(self):
        asyncio.run(self._async_main())

    async def _find_device(self):
        print(f"BLEデバイスを探しています: {self.device_name}")
        devices = await BleakScanner.discover(timeout=self.scan_timeout)

        for d in devices:
            if d.name == self.device_name:
                print(f"BLEデバイスを発見: {d.name} / {d.address}")
                return d

        print("BLEデバイスが見つかりませんでした。")
        return None

    async def _async_main(self):
        while not self.stop_event.is_set():
            target = await self._find_device()

            if target is None:
                self.is_connected = False
                await asyncio.sleep(2.0)
                continue

            try:
                async with BleakClient(target.address) as client:
                    self.is_connected = True
                    print(f"XIAO BLEに接続しました: {self.device_name}")

                    await client.write_gatt_char(
                        self.char_uuid,
                        bytes([self.requested_value]),
                        response=True,
                    )

                    while not self.stop_event.is_set():
                        try:
                            cmd = await asyncio.to_thread(self.cmd_queue.get, True, 0.5)
                        except queue.Empty:
                            if not client.is_connected:
                                print("BLE接続が切れました。再接続します。")
                                break
                            continue

                        if cmd is None:
                            break

                        await client.write_gatt_char(
                            self.char_uuid,
                            bytes([cmd]),
                            response=True,
                        )

                    if client.is_connected:
                        try:
                            await client.write_gatt_char(
                                self.char_uuid,
                                bytes([self.STATE_OFF]),
                                response=True,
                            )
                        except Exception:
                            pass

            except Exception as e:
                print("BLE通信エラー。再接続を試みます。")
                print(e)
                await asyncio.sleep(2.0)

            finally:
                self.is_connected = False

        print("BLEフィードバック制御を終了しました。")


# =========================
# StereoSetクラス
# ローカルに接続された2台カメラを使うセット
# =========================
class StereoSet:
    def __init__(self, name, calib_file, cam0_index, cam1_index, backend_mode):
        self.name = name
        self.calib_file = calib_file
        self.cam0_index = cam0_index
        self.cam1_index = cam1_index
        self.backend_mode = backend_mode

        data = np.load(calib_file)
        self.map0x = data["map0x"]
        self.map0y = data["map0y"]
        self.map1x = data["map1x"]
        self.map1y = data["map1y"]
        self.P0 = data["P0"]
        self.P1 = data["P1"]

        self.cap0 = open_camera(cam0_index, backend_mode)
        self.cap1 = open_camera(cam1_index, backend_mode)

        self.states = {}
        for color in COLOR_ORDER:
            self.states[color] = {
                "live": False,
                "live_point": None,
                "last_point": None,
                "current_point": None,
                "source": "NO DATA",
                "target": None,
                "y_diff": None,
                "msg0": f"{color}: not found",
                "msg1": f"{color}: not found",
                "msg_color0": (0, 0, 255),
                "msg_color1": (0, 0, 255),
            }

        self.out0 = None
        self.out1 = None

    def read_and_process(self):
        ret0, frame0 = self.cap0.read()
        ret1, frame1 = self.cap1.read()

        if not ret0 or frame0 is None:
            raise RuntimeError(f"{self.name} Cam0 index={self.cam0_index} のフレーム取得に失敗しました。")
        if not ret1 or frame1 is None:
            raise RuntimeError(f"{self.name} Cam1 index={self.cam1_index} のフレーム取得に失敗しました。")

        rect0 = cv2.remap(frame0, self.map0x, self.map0y, cv2.INTER_LINEAR)
        rect1 = cv2.remap(frame1, self.map1x, self.map1y, cv2.INTER_LINEAR)

        self.out0 = draw_horizontal_guides(rect0)
        self.out1 = draw_horizontal_guides(rect1)

        for color in COLOR_ORDER:
            cfg = COLOR_CONFIGS[color]

            _, res0, msg0, msg_color0 = detect_color_center(rect0, self.out0, color)
            _, res1, msg1, msg_color1 = detect_color_center(rect1, self.out1, color)

            data_3d = get_marker_3d(res0, res1, self.P0, self.P1)

            st = self.states[color]
            st["msg0"] = msg0
            st["msg1"] = msg1
            st["msg_color0"] = msg_color0
            st["msg_color1"] = msg_color1

            if data_3d is not None:
                point = data_3d["point_3d"].copy()

                st["live"] = True
                st["live_point"] = point
                st["last_point"] = point.copy()
                st["current_point"] = point
                st["source"] = "LIVE"
                st["y_diff"] = data_3d["y_diff"]

                cv2.line(
                    self.out0,
                    (0, data_3d["cy0"]),
                    (self.out0.shape[1] - 1, data_3d["cy0"]),
                    cfg["box_color"],
                    1,
                )
                cv2.line(
                    self.out1,
                    (0, data_3d["cy1"]),
                    (self.out1.shape[1] - 1, data_3d["cy1"]),
                    cfg["box_color"],
                    1,
                )

            else:
                st["live"] = False
                st["live_point"] = None
                st["y_diff"] = None

                if st["last_point"] is not None:
                    st["current_point"] = st["last_point"].copy()
                    st["source"] = "LAST"
                else:
                    st["current_point"] = None
                    st["source"] = "NO DATA"

    def set_targets_from_current(self):
        saved = []
        missing = []

        for color in COLOR_ORDER:
            point = self.states[color]["current_point"]

            if point is None:
                self.states[color]["target"] = None
                missing.append(color)
            else:
                self.states[color]["target"] = point.copy()
                saved.append(color)

        return saved, missing

    def reset_targets(self):
        for color in COLOR_ORDER:
            self.states[color]["target"] = None

    def release(self):
        self.cap0.release()
        self.cap1.release()

    def make_display_pair(self):
        disp0 = maybe_flip_for_display(self.out0.copy())
        disp1 = maybe_flip_for_display(self.out1.copy())

        cv2.putText(
            disp0,
            f"{self.name} Cam0 Index {self.cam0_index}",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 255),
            2,
        )
        cv2.putText(
            disp1,
            f"{self.name} Cam1 Index {self.cam1_index}",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 255),
            2,
        )

        y = 55
        for color in COLOR_ORDER:
            st = self.states[color]
            cv2.putText(
                disp0,
                st["msg0"],
                (10, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                st["msg_color0"],
                1,
            )
            cv2.putText(
                disp1,
                st["msg1"],
                (10, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                st["msg_color1"],
                1,
            )
            y += 22

        return np.hstack((resize_view(disp0), resize_view(disp1)))


# =========================
# RemoteBSetクラス
# サブPCからUDPで届くBセット3D座標を扱う
# =========================
class RemoteBSet:
    def __init__(self, name="B_REMOTE", udp_ip="0.0.0.0", udp_port=5005):
        self.name = name
        self.udp_ip = udp_ip
        self.udp_port = udp_port

        self.states = {}
        for color in COLOR_ORDER:
            self.states[color] = {
                "live": False,
                "live_point": None,
                "last_point": None,
                "current_point": None,
                "source": "NO DATA",
                "target": None,
                "y_diff": None,
                "msg0": f"{color}: waiting UDP",
                "msg1": f"{color}: waiting UDP",
                "msg_color0": (0, 0, 255),
                "msg_color1": (0, 0, 255),
            }

        self.latest_packet = None
        self.latest_receive_time = 0.0
        self.frame = -1
        self.sender_addr = None

        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._udp_thread_main, daemon=True)
        self.thread.start()

    def _udp_thread_main(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.udp_ip, self.udp_port))
        sock.settimeout(0.5)

        print("======================================")
        print("Remote B UDP receiver started")
        print(f"Listening on {self.udp_ip}:{self.udp_port}")
        print("======================================")

        while not self.stop_event.is_set():
            try:
                data, addr = sock.recvfrom(65535)

            except socket.timeout:
                continue

            except Exception as e:
                print("[RemoteB UDP error]", e)
                continue

            try:
                text = data.decode("utf-8", errors="replace")
                packet = json.loads(text)

                if packet.get("type") != "bset_3d":
                    continue

                with self.lock:
                    self.latest_packet = packet
                    self.latest_receive_time = time.time()
                    self.frame = packet.get("frame", -1)
                    self.sender_addr = addr

            except Exception as e:
                print("[RemoteB JSON error]", e)

        sock.close()
        print("Remote B UDP receiver stopped")

    def read_and_process(self):
        """
        StereoSetと同じようにメインループから毎フレーム呼ばれる。
        カメラは読まず、UDPで受け取った最新B座標をstatesに反映する。
        """
        with self.lock:
            packet = self.latest_packet
            receive_age = time.time() - self.latest_receive_time if self.latest_receive_time > 0 else 999.0

        if packet is None or receive_age > 1.0:
            for color in COLOR_ORDER:
                st = self.states[color]

                st["live"] = False
                st["live_point"] = None
                st["y_diff"] = None

                if st["last_point"] is not None and receive_age <= LOST_HOLD_SEC:
                    st["current_point"] = st["last_point"].copy()
                    st["source"] = "LAST"
                else:
                    st["current_point"] = None
                    st["source"] = "NO DATA"

                st["msg0"] = f"{color}: UDP waiting"
                st["msg1"] = f"{color}: UDP waiting"
                st["msg_color0"] = (0, 0, 255)
                st["msg_color1"] = (0, 0, 255)

            return

        colors = packet.get("colors", {})

        for color in COLOR_ORDER:
            st = self.states[color]
            cdata = colors.get(color, {})

            live = bool(cdata.get("live", False))
            point = cdata.get("point", None)
            y_diff = cdata.get("y_diff", None)

            if live and point is not None:
                point_np = np.array(point, dtype=np.float64)

                st["live"] = True
                st["live_point"] = point_np
                st["last_point"] = point_np.copy()
                st["current_point"] = point_np
                st["source"] = "B_LIVE"
                st["y_diff"] = y_diff

                st["msg0"] = f"{color}: UDP LIVE"
                st["msg1"] = f"{color}: {format_vec(point_np)}"
                st["msg_color0"] = (255, 255, 255)
                st["msg_color1"] = (255, 255, 255)

            else:
                st["live"] = False
                st["live_point"] = None
                st["y_diff"] = None

                if st["last_point"] is not None:
                    st["current_point"] = st["last_point"].copy()
                    st["source"] = "LAST"
                    st["msg0"] = f"{color}: UDP lost, using LAST"
                    st["msg1"] = f"{color}: LAST"
                    st["msg_color0"] = (0, 255, 255)
                    st["msg_color1"] = (0, 255, 255)

                else:
                    st["current_point"] = None
                    st["source"] = "NO DATA"
                    st["msg0"] = f"{color}: UDP not found"
                    st["msg1"] = f"{color}: UDP not found"
                    st["msg_color0"] = (0, 0, 255)
                    st["msg_color1"] = (0, 0, 255)

    def set_targets_from_current(self):
        saved = []
        missing = []

        for color in COLOR_ORDER:
            point = self.states[color]["current_point"]

            if point is None:
                self.states[color]["target"] = None
                missing.append(color)
            else:
                self.states[color]["target"] = point.copy()
                saved.append(color)

        return saved, missing

    def reset_targets(self):
        for color in COLOR_ORDER:
            self.states[color]["target"] = None

    def release(self):
        self.stop_event.set()

        if self.thread is not None:
            self.thread.join(timeout=2.0)

    def make_display_pair(self):
        row = np.full((VIEW_H, VIEW_W * 2, 3), 25, dtype=np.uint8)

        cv2.putText(
            row,
            "B SET from SUB PC / UDP",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
        )

        age = time.time() - self.latest_receive_time if self.latest_receive_time > 0 else 999.0
        age_color = (0, 255, 0) if age < 1.0 else (0, 0, 255)

        sender_text = str(self.sender_addr) if self.sender_addr is not None else "---"

        cv2.putText(
            row,
            f"UDP age: {age:.2f}s  frame: {self.frame}",
            (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            age_color,
            2,
        )

        cv2.putText(
            row,
            f"sender: {sender_text}",
            (10, 82),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (180, 180, 180),
            1,
        )

        y = 115
        for color in COLOR_ORDER:
            st = self.states[color]
            point_text = format_vec(st["current_point"])
            text = f"{color}: {st['source']} {point_text}"

            cv2.putText(
                row,
                text,
                (10, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                COLOR_CONFIGS[color]["text_color"],
                1,
            )
            y += 28

        return row


# =========================
# 最終判定ロジック
# =========================
def select_and_judge_color(color, set_a, set_b, last_used):
    """
    ルール:
    USE_B_SET=True の場合
      1. AでLIVE検出できている -> A現在座標 vs A目標座標
      2. AでLIVE検出できないがBでLIVE検出できている -> B現在座標 vs B目標座標
      3. A/BどちらもLIVE検出できない -> 最後に使用した判定情報

    USE_B_SET=False の場合
      1. AでLIVE検出できている -> A現在座標 vs A目標座標
      2. AでLIVE検出できない -> 最後に使用した判定情報
    """
    a_st = set_a.states[color]
    b_st = set_b.states[color] if set_b is not None else None

    selected = None

    if a_st["live"] and a_st["target"] is not None:
        selected = {
            "used_set": "A",
            "current": a_st["live_point"],
            "target": a_st["target"],
            "source": "A_LIVE",
            "y_diff": a_st["y_diff"],
        }

    elif b_st is not None and b_st["live"] and b_st["target"] is not None:
        selected = {
            "used_set": "B",
            "current": b_st["live_point"],
            "target": b_st["target"],
            "source": "B_LIVE",
            "y_diff": b_st["y_diff"],
        }

    elif last_used[color] is not None:
        age = time.time() - last_used[color]["time"]

        if age <= LOST_HOLD_SEC:
            selected = {
                "used_set": last_used[color]["used_set"],
                "current": last_used[color]["current"],
                "target": last_used[color]["target"],
                "source": "LAST_USED",
                "y_diff": None,
                "age": age,
            }
        else:
            last_used[color] = None

    if selected is None:
        return {
            "used_set": "-",
            "source": "NO DATA",
            "current": None,
            "target": None,
            "distance": None,
            "inside": False,
            "judge_text": "NO DATA",
            "judge_color": (0, 0, 255),
            "y_diff": None,
        }

    distance, inside, judge_text, judge_color = judge_distance(
        selected["current"],
        selected["target"],
    )

    if selected["source"] in ["A_LIVE", "B_LIVE"]:
        last_used[color] = {
            "used_set": selected["used_set"],
            "current": selected["current"].copy(),
            "target": selected["target"].copy(),
            "time": time.time(),
        }

    return {
        "used_set": selected["used_set"],
        "source": selected["source"],
        "current": selected["current"],
        "target": selected["target"],
        "distance": distance,
        "inside": inside,
        "judge_text": judge_text,
        "judge_color": judge_color,
        "y_diff": selected["y_diff"],
        "last_age": selected.get("age", 0.0),
    }


def targets_ready(set_a, set_b):
    """
    USE_B_SET=True:
      各色について、AまたはBのどちらかに目標があればOK。

    USE_B_SET=False:
      各色について、Aに目標があればOK。
    """
    for color in COLOR_ORDER:
        a_target = set_a.states[color]["target"]

        if set_b is None:
            if a_target is None:
                return False
        else:
            b_target = set_b.states[color]["target"]
            if a_target is None and b_target is None:
                return False

    return True


# =========================
# メイン処理
# =========================
def main():
    print("======================================")
    print("PoseRing 2PC Main / A Camera + Remote B UDP")
    print("Aセット優先、Aで見失った色だけBセットで補助")
    print("q / Esc : 終了")
    print("s       : A/B両方の現在4色座標を目標として保存 + 出題時写真保存（まだゲーム開始しない）")
    print("g       : ゲーム開始 / クリア時間計測スタート")
    print("clear  : ALL CLEAR時にクリア時写真保存 + 比較画像表示")
    print("c       : 目標とCLEAR状態をリセット")
    print("r       : 目標・最後に使った判定情報・CLEAR状態をすべてリセット")
    print("0/1/2   : BLEテスト")
    print("a       : BLE自動制御に戻す")
    print("======================================")
    print("A_CALIB_FILE:", A_CALIB_FILE)
    print("B_CALIB_FILE:", B_CALIB_FILE)
    print(f"A cameras: {A_CAM0_INDEX}, {A_CAM1_INDEX}")
    print(f"B cameras: {B_CAM0_INDEX}, {B_CAM1_INDEX}")
    print(f"A backend: {A_BACKEND}")
    print(f"B backend: {B_BACKEND}")
    print(f"USE_B_SET: {USE_B_SET}")
    print(f"USE_REMOTE_B_SET: {USE_REMOTE_B_SET}")
    print(f"REMOTE_B_UDP_IP: {REMOTE_B_UDP_IP}")
    print(f"REMOTE_B_UDP_PORT: {REMOTE_B_UDP_PORT}")
    print(f"ENABLE_XIAO_BLE: {ENABLE_XIAO_BLE}")
    print(f"BLE_DEVICE_NAME: {BLE_DEVICE_NAME}")
    print(f"FEEDBACK_TARGET_COLOR: {FEEDBACK_TARGET_COLOR}")
    print("======================================")

    set_a = StereoSet("A", A_CALIB_FILE, A_CAM0_INDEX, A_CAM1_INDEX, A_BACKEND)

    if USE_B_SET:
        if USE_REMOTE_B_SET:
            set_b = RemoteBSet("B", REMOTE_B_UDP_IP, REMOTE_B_UDP_PORT)
        else:
            set_b = StereoSet("B", B_CALIB_FILE, B_CAM0_INDEX, B_CAM1_INDEX, B_BACKEND)
    else:
        set_b = None

    ble_feedback = None
    if ENABLE_XIAO_BLE:
        ble_feedback = BleFeedbackController(BLE_DEVICE_NAME, BLE_LED_CHAR_UUID)
        ble_feedback.start()

    last_used = {color: None for color in COLOR_ORDER}
    final_states = {}

    all_inside_start_time = None
    overall_clear = False
    hold_elapsed = 0.0

    # ゲーム開始/クリア時間計測
    # sキーではお題を保存するだけで、gキーを押すまでゲームは開始しない。
    game_active = False
    game_start_time = None
    clear_time = None
    clear_logged = False

    # None=自動, 1=白固定, 2-255=赤輝度固定, 0=消灯固定
    force_ble_state = None

    # ステージ内外LED制御用。
    # 対象色が最後にLIVE検出された時刻を保持し、短時間の遮蔽では消灯しない。
    last_target_live_time = None
    target_stage_lost_age = None

    # 写真保存用
    photo_session_dir = None
    challenge_photo_image = None
    clear_photo_image = None
    result_display_image = None
    challenge_photo_path = None
    clear_photo_path = None
    comparison_photo_path = None

    try:
        while True:
            set_a.read_and_process()

            if set_b is not None:
                set_b.read_and_process()

            ready = targets_ready(set_a, set_b)

            # A優先・B補助で最終判定
            for color in COLOR_ORDER:
                final_states[color] = select_and_judge_color(color, set_a, set_b, last_used)

            # =========================
            # XIAO BLEフィードバック
            # =========================
            target_color = FEEDBACK_TARGET_COLOR
            target_state = final_states.get(target_color)

            target_goal_ready = (
                set_a.states[target_color]["target"] is not None
                or (set_b is not None and set_b.states[target_color]["target"] is not None)
            )

            # ステージ内外判定:
            # A/Bどちらかのカメラセットで対象色がLIVE検出されていれば「ステージ内」
            # LAST_USEDは、見失い補助には使うが、ステージ内外判定には使わない。
            target_live_in_stage = bool(
                target_state
                and target_state["source"] in ["A_LIVE", "B_LIVE"]
            )

            # 遮蔽猶予付きのステージ内判定。
            # target_live_in_stage は「今この瞬間に見えているか」。
            # target_stage_visible は「今見えている、または直近 STAGE_LOST_GRACE_SEC 秒以内に見えていたか」。
            stage_now = time.time()
            if target_live_in_stage:
                last_target_live_time = stage_now
                target_stage_lost_age = 0.0
                target_stage_visible = True
            else:
                if last_target_live_time is None:
                    target_stage_lost_age = None
                    target_stage_visible = False
                else:
                    target_stage_lost_age = stage_now - last_target_live_time
                    target_stage_visible = target_stage_lost_age <= STAGE_LOST_GRACE_SEC

            if STAGE_VISIBLE_REQUIRES_LIVE:
                target_visible = target_live_in_stage
            elif REQUIRE_TARGET_LIVE_FOR_LED:
                target_visible = target_live_in_stage
            else:
                target_visible = bool(
                    target_state
                    and target_state["source"] in ["A_LIVE", "B_LIVE", "LAST_USED"]
                )

            target_distance = target_state["distance"] if target_state else None
            target_inside = bool(target_state and target_state["inside"])

            if game_active and target_goal_ready and target_visible and target_distance is not None:
                if target_inside:
                    red_brightness = FEEDBACK_MAX_RED_BRIGHTNESS
                else:
                    red_brightness = distance_to_red_brightness(target_distance)
            else:
                red_brightness = None

            # BLE送信値の最終決定
            #   ステージ外: 0 = OFF
            #   ステージ内・まだ赤フィードバックなし: 1 = WHITE
            #   ステージ内・ゴール接近/ゴール内: 2-255 = RED brightness
            if ENABLE_STAGE_VISIBLE_LED:
                if not target_stage_visible:
                    auto_ble_state = BleFeedbackController.STATE_OFF
                elif red_brightness is None:
                    auto_ble_state = BleFeedbackController.STATE_CONNECTED_WHITE
                else:
                    auto_ble_state = max(
                        BleFeedbackController.MIN_RED_BRIGHTNESS_VALUE,
                        min(255, int(red_brightness)),
                    )
            else:
                if red_brightness is None:
                    auto_ble_state = BleFeedbackController.STATE_CONNECTED_WHITE
                else:
                    auto_ble_state = max(
                        BleFeedbackController.MIN_RED_BRIGHTNESS_VALUE,
                        min(255, int(red_brightness)),
                    )

            if ble_feedback is not None:
                if force_ble_state is None:
                    ble_feedback.set_state(auto_ble_state)
                else:
                    ble_feedback.set_state(force_ble_state)

            target_feedback_on = red_brightness is not None

            all_inside = ready and all(final_states[color]["inside"] for color in COLOR_ORDER)

            # =========================
            # ゲーム進行 / クリア時間計測
            # =========================
            # sキーで目標座標を保存しただけではゲームは開始しない。
            # gキーで game_active=True になってから、HOLD判定とタイマーを動かす。
            if game_active and ready and not overall_clear:
                if all_inside:
                    if all_inside_start_time is None:
                        all_inside_start_time = time.time()

                    hold_elapsed = time.time() - all_inside_start_time

                    if hold_elapsed >= HOLD_TIME_SEC:
                        overall_clear = True
                        game_active = False
                        clear_time = time.time() - game_start_time if game_start_time is not None else None

                        if ENABLE_PHOTO_CAPTURE:
                            if photo_session_dir is None:
                                photo_session_dir = create_photo_session_dir()

                            clear_photo_image = make_photo_from_a_set(
                                set_a,
                                "CLEAR POSE",
                                f"Clear Time: {clear_time:.2f} sec" if clear_time is not None else "Clear Time: ---",
                            )
                            clear_photo_path = save_photo_image(
                                clear_photo_image,
                                photo_session_dir,
                                "clear_pose_" + get_timestamp_for_filename() + ".jpg",
                            )

                            result_display_image = make_comparison_photo(
                                challenge_photo_image,
                                clear_photo_image,
                                clear_time,
                            )
                            comparison_photo_path = save_photo_image(
                                result_display_image,
                                photo_session_dir,
                                "comparison_" + get_timestamp_for_filename() + ".jpg",
                            )

                            if result_display_image is not None:
                                show_photo_window_safely(result_display_image)

                        if not clear_logged:
                            print("======================================")
                            if clear_time is not None:
                                print(f"ALL CLEAR! clear_time={clear_time:.2f} sec")
                            else:
                                print("ALL CLEAR!")
                            if challenge_photo_path is not None:
                                print("出題時写真:", challenge_photo_path)
                            if clear_photo_path is not None:
                                print("クリア時写真:", clear_photo_path)
                            if comparison_photo_path is not None:
                                print("比較画像:", comparison_photo_path)
                            print("======================================")
                            clear_logged = True

                else:
                    all_inside_start_time = None
                    hold_elapsed = 0.0
            else:
                # ゲーム開始前、クリア後、またはターゲット未設定時はHOLDを進めない。
                if not overall_clear:
                    all_inside_start_time = None
                    hold_elapsed = 0.0

            elapsed_text = "---"
            if game_active and game_start_time is not None:
                elapsed_text = f"{time.time() - game_start_time:.2f}s"
            elif clear_time is not None:
                elapsed_text = f"{clear_time:.2f}s"

            if overall_clear:
                if clear_time is not None:
                    overall_text = f"ALL CLEAR! TIME {clear_time:.2f}s"
                else:
                    overall_text = "ALL CLEAR!"
                overall_color = (0, 255, 0)
            elif not ready:
                overall_text = "NO TARGET | Press s to set A/B targets"
                overall_color = (0, 200, 255)
            elif not game_active:
                overall_text = "TARGET SET | Press g to START"
                overall_color = (255, 200, 0)
            elif all_inside:
                overall_text = f"HOLD {hold_elapsed:.1f}/{HOLD_TIME_SEC:.1f}s | TIME {elapsed_text}"
                overall_color = (0, 255, 255)
            else:
                overall_text = f"PLAYING | TIME {elapsed_text}"
                overall_color = (0, 255, 255)

            # =========================
            # 表示作成
            # =========================
            row_a = set_a.make_display_pair()

            if set_b is not None:
                row_b = set_b.make_display_pair()
            else:
                row_b = np.zeros_like(row_a)
                cv2.putText(
                    row_b,
                    "B SET disabled",
                    (180, 120),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 255),
                    2,
                )

            cv2.rectangle(
                row_a,
                (5, row_a.shape[0] - 30),
                (70, row_a.shape[0] - 5),
                (0, 0, 0),
                -1,
            )
            cv2.putText(
                row_a,
                "A SET",
                (10, row_a.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 255),
                2,
            )

            cv2.rectangle(
                row_b,
                (5, row_b.shape[0] - 30),
                (120, row_b.shape[0] - 5),
                (0, 0, 0),
                -1,
            )
            cv2.putText(
                row_b,
                "B SET",
                (10, row_b.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 255),
                2,
            )

            cameras_left = np.vstack((row_a, row_b))

            info_h = cameras_left.shape[0]
            info_w = 640
            info = np.full((info_h, info_w, 3), 25, dtype=np.uint8)

            # ヘッダー
            cv2.rectangle(info, (0, 0), (info_w, 45), (50, 40, 30), -1)
            cv2.putText(
                info,
                "PoseRing: 2PC Main / A Camera + Remote B",
                (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
            )

            cv2.putText(
                info,
                "Rule: A_LIVE -> B_LIVE -> LAST_USED (Coords not mixed)",
                (15, 70),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (180, 180, 180),
                1,
            )
            cv2.putText(
                info,
                "[s] Set Target [g] Start Game [c] Reset [r] Reset All [0/1/2] BLE test [a] Auto [q] Quit",
                (15, 95),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
            )

            # 表ヘッダー
            table_y_start = 125
            cv2.line(info, (15, table_y_start), (625, table_y_start), (100, 100, 100), 1)

            col_x = [15, 110, 220, 310, 420, 520]

            cv2.putText(info, "COLOR", (col_x[0], 145), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
            cv2.putText(info, "SOURCE", (col_x[1], 145), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
            cv2.putText(info, "SET", (col_x[2], 145), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
            cv2.putText(info, "DISTANCE", (col_x[3], 145), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
            cv2.putText(info, "STATUS", (col_x[4], 145), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
            cv2.putText(info, "Y-ERR", (col_x[5], 145), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)

            cv2.line(info, (15, 155), (625, 155), (100, 100, 100), 1)

            # 表データ
            y = 185
            for i, color in enumerate(COLOR_ORDER):
                fs = final_states[color]
                c_conf = COLOR_CONFIGS[color]

                if i % 2 == 1:
                    cv2.rectangle(info, (15, y - 20), (625, y + 10), (35, 35, 35), -1)

                dist_text = f"{fs['distance']:.1f} mm" if fs["distance"] is not None else "---"
                ydiff_text = f"{fs['y_diff']:.1f} px" if fs["y_diff"] is not None else "---"

                cv2.putText(info, color, (col_x[0], y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, c_conf["text_color"], 2)
                cv2.putText(info, fs["source"], (col_x[1], y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)
                cv2.putText(info, fs["used_set"], (col_x[2], y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)
                cv2.putText(info, dist_text, (col_x[3], y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
                cv2.putText(info, fs["judge_text"], (col_x[4], y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, fs["judge_color"], 2)
                cv2.putText(info, ydiff_text, (col_x[5], y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

                y += 45

            cv2.line(info, (15, 350), (625, 350), (100, 100, 100), 1)

            # Overall
            box_start = (15, 380)
            box_end = (625, 460)
            cv2.rectangle(info, box_start, box_end, (40, 40, 40), -1)
            cv2.rectangle(info, box_start, box_end, overall_color, 2)

            cv2.putText(
                info,
                f"OVERALL:  {overall_text}",
                (30, 420),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                overall_color,
                2,
            )

            if game_start_time is None and clear_time is None:
                timer_text = "TIMER: ---"
            elif game_active and game_start_time is not None:
                timer_text = f"TIMER: {time.time() - game_start_time:.2f} sec"
            elif clear_time is not None:
                timer_text = f"CLEAR TIME: {clear_time:.2f} sec"
            else:
                timer_text = "TIMER: waiting"

            cv2.putText(
                info,
                timer_text,
                (30, 450),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )

            if force_ble_state is not None:
                ble_text = f"BLE LED: FORCE {force_ble_state} (0/1/2, a=auto)"
                ble_color = (255, 200, 0)

            elif target_feedback_on:
                if target_state and target_state["inside"]:
                    ble_text = f"BLE LED: SEND 255 {FEEDBACK_TARGET_COLOR} GOAL"
                else:
                    ble_text = f"BLE LED: SEND {red_brightness} {FEEDBACK_TARGET_COLOR} NEAR"
                ble_color = (0, 255, 255)

            elif ble_feedback is not None and ble_feedback.is_connected:
                if ENABLE_STAGE_VISIBLE_LED and not target_stage_visible:
                    ble_text = f"BLE LED: SEND 0 OFF / {FEEDBACK_TARGET_COLOR} OUT OF STAGE"
                    ble_color = (120, 120, 120)
                elif ENABLE_STAGE_VISIBLE_LED and not target_live_in_stage:
                    age_text = "---" if target_stage_lost_age is None else f"{target_stage_lost_age:.1f}s"
                    ble_text = f"BLE LED: SEND 1 WHITE / {FEEDBACK_TARGET_COLOR} LOST GRACE {age_text}"
                    ble_color = (255, 255, 255)
                else:
                    ble_text = f"BLE LED: SEND 1 WHITE / {FEEDBACK_TARGET_COLOR} IN STAGE"
                    ble_color = (255, 255, 255)

            else:
                ble_text = "BLE LED: SEARCHING/OFF"
                ble_color = (120, 120, 120)

            cv2.putText(
                info,
                ble_text,
                (420, 430),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                ble_color,
                2,
            )

            display = np.hstack((cameras_left, info))
            cv2.imshow("PoseRing 2PC Main", display)

            if result_display_image is not None and overall_clear:
                show_photo_window_safely(result_display_image)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q") or key == 27:
                break

            # BLE送信の動作確認用
            if key == ord("0"):
                force_ble_state = BleFeedbackController.STATE_OFF
                print("[BLE TEST] force OFF: send 0")

            if key == ord("1"):
                force_ble_state = BleFeedbackController.STATE_CONNECTED_WHITE
                print("[BLE TEST] force WHITE: send 1")

            if key == ord("2"):
                force_ble_state = FEEDBACK_MAX_RED_BRIGHTNESS
                print("[BLE TEST] force RED MAX: send 255")

            if key == ord("a"):
                force_ble_state = None
                print("[BLE TEST] auto mode")

            if key == ord("g"):
                if not targets_ready(set_a, set_b):
                    print("ゲーム開始できません。先に s キーで4色の目標座標を保存してください。")
                else:
                    last_used = {color: None for color in COLOR_ORDER}
                    all_inside_start_time = None
                    hold_elapsed = 0.0
                    overall_clear = False
                    game_active = True
                    game_start_time = time.time()
                    clear_time = None
                    clear_logged = False
                    clear_photo_image = None
                    result_display_image = None
                    clear_photo_path = None
                    comparison_photo_path = None
                    close_photo_window_safely()

                    print("======================================")
                    print("ゲーム開始。クリア時間計測を開始しました。")
                    print("======================================")

            if key == ord("s"):
                saved_a, missing_a = set_a.set_targets_from_current()

                if set_b is not None:
                    saved_b, missing_b = set_b.set_targets_from_current()
                else:
                    saved_b, missing_b = [], COLOR_ORDER.copy()

                missing_both = []
                for color in COLOR_ORDER:
                    a_target = set_a.states[color]["target"]

                    if set_b is None:
                        if a_target is None:
                            missing_both.append(color)

                    else:
                        b_target = set_b.states[color]["target"]

                        if a_target is None and b_target is None:
                            missing_both.append(color)

                last_used = {color: None for color in COLOR_ORDER}
                all_inside_start_time = None
                hold_elapsed = 0.0
                overall_clear = False
                game_active = False
                game_start_time = None
                clear_time = None
                clear_logged = False

                photo_session_dir = None
                challenge_photo_image = None
                clear_photo_image = None
                result_display_image = None
                challenge_photo_path = None
                clear_photo_path = None
                comparison_photo_path = None
                close_photo_window_safely()

                if ENABLE_PHOTO_CAPTURE:
                    photo_session_dir = create_photo_session_dir()
                    challenge_photo_image = make_photo_from_a_set(
                        set_a,
                        "CHALLENGE / TARGET POSE",
                        "Saved when s key was pressed",
                    )
                    challenge_photo_path = save_photo_image(
                        challenge_photo_image,
                        photo_session_dir,
                        "challenge_pose_" + get_timestamp_for_filename() + ".jpg",
                    )

                print("======================================")
                print("A/Bの目標座標を保存しました。まだゲームは開始していません。")
                print("A saved:", saved_a, "| A missing:", missing_a)
                print("B saved:", saved_b, "| B missing:", missing_b)
                if challenge_photo_path is not None:
                    print("出題時写真:", challenge_photo_path)

                if missing_both:
                    print("注意: A/Bどちらにも目標がない色があります:", missing_both)
                    print("この色は判定できないため、もう一度見える位置で s を押してください。")
                else:
                    print("4色すべてについて、AまたはBに目標座標があります。")
                    print("準備ができたら g キーでゲーム開始・タイマー開始します。")

                for color in COLOR_ORDER:
                    print(f"[{color}]")
                    print("  A target:", format_vec(set_a.states[color]["target"]))

                    if set_b is not None:
                        print("  B target:", format_vec(set_b.states[color]["target"]))
                    else:
                        print("  B target: disabled")

                print("======================================")

            if key == ord("c"):
                set_a.reset_targets()

                if set_b is not None:
                    set_b.reset_targets()

                last_used = {color: None for color in COLOR_ORDER}
                all_inside_start_time = None
                hold_elapsed = 0.0
                overall_clear = False
                game_active = False
                game_start_time = None
                clear_time = None
                clear_logged = False
                photo_session_dir = None
                challenge_photo_image = None
                clear_photo_image = None
                result_display_image = None
                challenge_photo_path = None
                clear_photo_path = None
                comparison_photo_path = None
                close_photo_window_safely()

                print("目標座標・ゲーム開始状態・CLEAR状態をリセットしました。")

            if key == ord("r"):
                set_a.reset_targets()

                if set_b is not None:
                    set_b.reset_targets()

                last_used = {color: None for color in COLOR_ORDER}
                all_inside_start_time = None
                hold_elapsed = 0.0
                overall_clear = False
                game_active = False
                game_start_time = None
                clear_time = None
                clear_logged = False
                photo_session_dir = None
                challenge_photo_image = None
                clear_photo_image = None
                result_display_image = None
                challenge_photo_path = None
                clear_photo_path = None
                comparison_photo_path = None
                close_photo_window_safely()

                print("目標座標・最後に使った判定情報・ゲーム開始状態・CLEAR状態をすべてリセットしました。")

    finally:
        if ble_feedback is not None:
            ble_feedback.set_state(BleFeedbackController.STATE_OFF)
            time.sleep(0.3)
            ble_feedback.stop()

        set_a.release()

        if set_b is not None:
            set_b.release()

        cv2.destroyAllWindows()
        print("終了しました。")


if __name__ == "__main__":
    main()