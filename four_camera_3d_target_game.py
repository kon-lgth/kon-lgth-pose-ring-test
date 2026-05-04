import cv2
import numpy as np
import time

# ============================================================
# PoseRing 4 Camera / 2 Stereo Sets Target Game
#
# Aセットを基本に使い、Aで見失った色だけBセットで補助します。
# A/Bの3D座標は直接混ぜません。
# Aを使う色は A現在座標 vs A目標座標、
# Bを使う色は B現在座標 vs B目標座標 で判定します。
# ============================================================

# =========================
# 設定
# =========================
# Aセット用キャリブレーション結果
# ※ Aセットを再キャリブレーションした場合はここを書き換える
A_CALIB_FILE = r"calibration_images\calib_A_20260504_143905\stereo_calibration_result.npz"
# Bセット用キャリブレーション結果
B_CALIB_FILE = r"calibration_images\calib_B_20260504_140722\stereo_calibration_result.npz"

A_CAM0_INDEX = 2
A_CAM1_INDEX = 3

B_CAM0_INDEX = 4
B_CAM1_INDEX = 5

# 表示設定
DISPLAY_MIRROR = True
VIEW_W = 320
VIEW_H = 240

# カメラ設定
CAPTURE_W = 640
CAPTURE_H = 480
FPS = 15

# Aセットは capture_calibration_pairs.py と同じ通常方式で開く
# Bセットは以前成功した DSHOW 方式で開く
A_BACKEND = "DEFAULT"
B_BACKEND = "DSHOW"

# 判定設定
CLEAR_DISTANCE_MM = 390.0   # 目標からこの距離以内ならOK
HOLD_TIME_SEC = 2.0         # 4色すべてOKをこの秒数キープしたらCLEAR

# =========================
# 安定化設定
# =========================
# A/BどちらもLIVEで取れなくなったとき、最後に使った判定情報を使う最大時間
LOST_HOLD_SEC = 0.7

# 1フレームでこの距離以上3D座標が飛んだ場合は誤検出として採用しない
MAX_JUMP_MM = 1300.0

# ステレオ補正後、左右画像の対応点のy座標差が大きすぎる場合は誤対応として採用しない
MAX_EPIPOLAR_Y_DIFF_PX = 25.0

# 座標を少しだけ平滑化する。1.0なら平滑化なし、0.0に近いほど遅くなる
SMOOTHING_ALPHA = 0.45

# マスク表示の初期状態。mキーでON/OFF切り替え
SHOW_MASK = False

# 色領域の最小面積
MIN_AREA = 200

# 色ごとの最小面積。まずは最新版のMIN_AREA=200を全色に適用し、色ごとに後から調整できる形にする。
MIN_AREA_BY_COLOR = {
    "RED": 200,
    "YELLOW": 200,
    "BLUE": 200,
    "GREEN": 200,
}

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
    AセットはDEFAULT、BセットはDSHOWのように分けて使う。
    """

    if backend_mode == "DSHOW":
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    elif backend_mode == "DEFAULT":
        cap = cv2.VideoCapture(index)
    else:
        raise ValueError("backend_mode must be 'DEFAULT' or 'DSHOW'")

    if not cap.isOpened():
        raise RuntimeError(f"カメラ index={index} を開けませんでした。backend={backend_mode}")

    # DEFAULTは、capture_calibration_pairs.py と同じように最低限の設定にする
    if backend_mode == "DEFAULT":
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_H)

    # DSHOWは、Bセットで安定していたMJPG設定を使う
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

    min_area = MIN_AREA_BY_COLOR[color_name]

    if area < min_area:
        return mask, None, f"{color_name}: small area={int(area)}<{min_area}", (0, 0, 255)

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


def accept_live_data(color_name, live_data, state, now):
    """
    3D座標の品質チェックを行い、採用できる座標だけをLIVEとして返す。

    チェック内容:
      1. epipolar y diff が大きすぎないか
      2. 前回の有効座標から急に飛んでいないか
      3. 採用時は座標を少し平滑化する
    """
    if live_data is None:
        return None, None, "not detected in both cameras"

    if live_data["y_diff"] > MAX_EPIPOLAR_Y_DIFF_PX:
        return None, None, f"bad y_diff {live_data['y_diff']:.1f}px"

    raw_point = live_data["point_3d"].copy()

    if state["last_point"] is not None:
        jump = float(np.linalg.norm(raw_point - state["last_point"]))
        if jump > MAX_JUMP_MM:
            return None, None, f"jump {jump:.0f}mm"

        point = SMOOTHING_ALPHA * raw_point + (1.0 - SMOOTHING_ALPHA) * state["last_point"]
    else:
        point = raw_point

    accepted_data = live_data.copy()
    accepted_data["point_3d"] = point
    accepted_data["raw_point_3d"] = raw_point
    return point, accepted_data, ""


def update_tracking_state(color_name, live_data, state, now):
    """
    LIVE / LAST / LOST / NO DATA を決める。

    - LIVE: 今フレームで両カメラから正しく3D座標を取れた
    - LAST: 今は見失ったが、最後に見えてから LOST_HOLD_SEC 秒以内なので最後の座標を使う
    - LOST: 最後に見えてから LOST_HOLD_SEC 秒を超えたので判定には使わない
    - NO DATA: まだ一度も有効な座標がない
    """
    accepted_point, accepted_data, reject_reason = accept_live_data(color_name, live_data, state, now)
    state["reject_reason"] = reject_reason

    if accepted_point is not None:
        state["live"] = True
        state["live_point"] = accepted_point.copy()
        state["last_point"] = accepted_point.copy()
        state["last_seen_time"] = now
        state["last_data"] = accepted_data
        state["current_point"] = accepted_point.copy()
        state["source"] = "LIVE"
        state["y_diff"] = accepted_data["y_diff"]
        return

    state["live"] = False
    state["live_point"] = None
    state["y_diff"] = None

    if state["last_point"] is None or state["last_seen_time"] is None:
        state["current_point"] = None
        state["source"] = "NO DATA"
        return

    age = now - state["last_seen_time"]
    if age <= LOST_HOLD_SEC:
        state["current_point"] = state["last_point"].copy()
        state["source"] = "LAST"
    else:
        state["current_point"] = None
        state["source"] = "LOST"


def judge_distance(current_3d, target_3d):
    if current_3d is None or target_3d is None:
        return None, False, "NO DATA", (0, 0, 255)

    distance = float(np.linalg.norm(current_3d - target_3d))

    if distance <= CLEAR_DISTANCE_MM:
        return distance, True, "OK", (0, 255, 0)
    if distance <= CLEAR_DISTANCE_MM * 2:
        return distance, False, "CLOSE", (0, 255, 255)
    return distance, False, "FAR", (0, 0, 255)


# =========================
# StereoSetクラス
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
                "live": False,           # 今フレームで両カメラ検出できたか
                "live_point": None,      # 今フレームで取得した3D座標
                "last_point": None,      # このセットで最後に採用した安定化済み3D座標
                "last_seen_time": None,  # 最後にLIVEとして採用した時刻
                "last_data": None,       # 最後にLIVEとして採用した詳細情報
                "current_point": None,   # 表示用。LIVEまたはLAST
                "source": "NO DATA",    # LIVE / LAST / LOST / NO DATA
                "target": None,          # このセット座標系での目標座標
                "y_diff": None,
                "reject_reason": "",
                "mask0": None,
                "mask1": None,
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

        now = time.time()

        for color in COLOR_ORDER:
            cfg = COLOR_CONFIGS[color]

            mask0, res0, msg0, msg_color0 = detect_color_center(rect0, self.out0, color)
            mask1, res1, msg1, msg_color1 = detect_color_center(rect1, self.out1, color)

            data_3d = get_marker_3d(res0, res1, self.P0, self.P1)

            st = self.states[color]
            st["mask0"] = mask0
            st["mask1"] = mask1
            st["msg0"] = msg0
            st["msg1"] = msg1
            st["msg_color0"] = msg_color0
            st["msg_color1"] = msg_color1

            update_tracking_state(color, data_3d, st, now)

            # LIVEとして採用できた場合だけ対応点確認用の水平線を描画
            if st["source"] == "LIVE" and st["last_data"] is not None:
                live = st["last_data"]
                cv2.line(self.out0, (0, live["cy0"]), (self.out0.shape[1] - 1, live["cy0"]), cfg["box_color"], 1)
                cv2.line(self.out1, (0, live["cy1"]), (self.out1.shape[1] - 1, live["cy1"]), cfg["box_color"], 1)

    def set_targets_from_current(self):
        """
        このセットで現在持っている座標を目標として保存する。
        LIVEがあればLIVE、なければLASTを使う。
        """
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

        cv2.putText(disp0, f"{self.name} Cam0 Index {self.cam0_index}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
        cv2.putText(disp1, f"{self.name} Cam1 Index {self.cam1_index}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)

        y = 55
        for color in COLOR_ORDER:
            st = self.states[color]
            cv2.putText(disp0, st["msg0"], (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, st["msg_color0"], 1)
            cv2.putText(disp1, st["msg1"], (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, st["msg_color1"], 1)
            y += 22

        return np.hstack((resize_view(disp0), resize_view(disp1)))


# =========================
# 最終判定ロジック
# =========================
def select_and_judge_color(color, set_a, set_b, last_used):
    """
    ルール:
    1. AでLIVE検出できている -> A現在座標 vs A目標座標
    2. AでLIVE検出できないがBでLIVE検出できている -> B現在座標 vs B目標座標
    3. A/BどちらもLIVE検出できない -> 最後に使用した判定情報
    """
    a_st = set_a.states[color]
    b_st = set_b.states[color]

    selected = None

    if a_st["live"] and a_st["target"] is not None:
        selected = {
            "used_set": "A",
            "current": a_st["live_point"],
            "target": a_st["target"],
            "source": "A_LIVE",
            "y_diff": a_st["y_diff"],
        }
    elif b_st["live"] and b_st["target"] is not None:
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

    distance, inside, judge_text, judge_color = judge_distance(selected["current"], selected["target"])

    # A/BのLIVEを使った場合だけ、最後に使った判定情報を更新する
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
    各色について、AまたはBのどちらかに目標があればOK。
    """
    for color in COLOR_ORDER:
        if set_a.states[color]["target"] is None and set_b.states[color]["target"] is None:
            return False
    return True


# =========================
# メイン処理
# =========================
def main():
    print("======================================")
    print("PoseRing Four Camera 3D Target Game")
    print("Aセット優先、Aで見失った色だけBセットで補助")
    print("q / Esc : 終了")
    print("s       : A/B両方の現在4色座標を目標として保存")
    print("c       : 目標とCLEAR状態をリセット")
    print("r       : 目標・最後に使った判定情報・CLEAR状態をすべてリセット")
    print("m       : マスク表示ON/OFF")
    print("======================================")
    print("A_CALIB_FILE:", A_CALIB_FILE)
    print("B_CALIB_FILE:", B_CALIB_FILE)
    print(f"A cameras: {A_CAM0_INDEX}, {A_CAM1_INDEX}")
    print(f"B cameras: {B_CAM0_INDEX}, {B_CAM1_INDEX}")
    print(f"A backend: {A_BACKEND}")
    print(f"B backend: {B_BACKEND}")
    print(f"LOST保持: {LOST_HOLD_SEC:.1f}s / 最大ジャンプ除外: {MAX_JUMP_MM:.0f}mm / 最大y差: {MAX_EPIPOLAR_Y_DIFF_PX:.0f}px / 平滑化alpha={SMOOTHING_ALPHA:.2f}")
    print("======================================")

    set_a = StereoSet("A", A_CALIB_FILE, A_CAM0_INDEX, A_CAM1_INDEX, A_BACKEND)
    set_b = StereoSet("B", B_CALIB_FILE, B_CAM0_INDEX, B_CAM1_INDEX, B_BACKEND)

    last_used = {color: None for color in COLOR_ORDER}
    final_states = {}

    all_inside_start_time = None
    overall_clear = False
    hold_elapsed = 0.0
    show_mask_runtime = SHOW_MASK

    try:
        while True:
            set_a.read_and_process()
            set_b.read_and_process()

            ready = targets_ready(set_a, set_b)

            # =========================
            # A優先・B補助で最終判定
            # =========================
            for color in COLOR_ORDER:
                final_states[color] = select_and_judge_color(color, set_a, set_b, last_used)

            all_inside = ready and all(final_states[color]["inside"] for color in COLOR_ORDER)

            if all_inside:
                if all_inside_start_time is None:
                    all_inside_start_time = time.time()
                hold_elapsed = time.time() - all_inside_start_time
                if hold_elapsed >= HOLD_TIME_SEC:
                    overall_clear = True
            else:
                all_inside_start_time = None
                hold_elapsed = 0.0
                overall_clear = False

            if overall_clear:
                overall_text = "ALL CLEAR!"
                overall_color = (0, 255, 0)
            elif not ready:
                overall_text = "NO TARGET | Press s to set A/B targets"
                overall_color = (0, 200, 255)
            elif all_inside:
                overall_text = f"HOLD {hold_elapsed:.1f}/{HOLD_TIME_SEC:.1f}s"
                overall_color = (0, 255, 255)
            else:
                overall_text = "PLAYING"
                overall_color = (0, 255, 255)

            # =========================
            # 表示作成 (左:カメラ、右:情報パネル - four_camera_3d_target_game.py と同じレイアウト)
            # =========================
            row_a = set_a.make_display_pair()
            row_b = set_b.make_display_pair()

            # A/Bラベル（背景を少し暗くして文字を読みやすく）
            cv2.rectangle(row_a, (5, row_a.shape[0] - 30), (70, row_a.shape[0] - 5), (0, 0, 0), -1)
            cv2.putText(row_a, "A SET", (10, row_a.shape[0] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

            cv2.rectangle(row_b, (5, row_b.shape[0] - 30), (70, row_b.shape[0] - 5), (0, 0, 0), -1)
            cv2.putText(row_b, "B SET", (10, row_b.shape[0] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

            # 左半分のカメラ映像 (高さ 480、幅 640)
            cameras_left = np.vstack((row_a, row_b))

            # 右半分の情報パネル (高さ480、幅640)
            info_h = cameras_left.shape[0]
            info_w = 640
            # 背景を真っ黒ではなく、視認性の高いダークグレー(25, 25, 25)にする
            info = np.full((info_h, info_w, 3), 25, dtype=np.uint8)

            # --- ヘッダー領域 ---
            # 上部にタイトル用の背景帯を描画
            cv2.rectangle(info, (0, 0), (info_w, 45), (50, 40, 30), -1)
            cv2.putText(info, "PoseRing: 4-Camera 3D Target Game", (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            # 操作説明とルール
            cv2.putText(info, "Rule: A_LIVE -> B_LIVE -> LAST_USED (Coords not mixed)", (15, 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
            cv2.putText(info, "[s] Set Target   [c] Reset Target   [r] Reset All   [q] Quit", (15, 95),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            # --- 表（テーブル）のヘッダー ---
            table_y_start = 125
            cv2.line(info, (15, table_y_start), (625, table_y_start), (100, 100, 100), 1)

            # 各カラムのX座標を固定して揃える
            col_x = [15, 110, 220, 310, 420, 520]

            cv2.putText(info, "COLOR",    (col_x[0], 145), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
            cv2.putText(info, "SOURCE",   (col_x[1], 145), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
            cv2.putText(info, "SET",      (col_x[2], 145), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
            cv2.putText(info, "DISTANCE", (col_x[3], 145), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
            cv2.putText(info, "STATUS",   (col_x[4], 145), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
            cv2.putText(info, "Y-ERR",    (col_x[5], 145), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)

            cv2.line(info, (15, 155), (625, 155), (100, 100, 100), 1)

            # --- 表（テーブル）のデータ行 ---
            y = 185
            for i, color in enumerate(COLOR_ORDER):
                fs = final_states[color]
                c_conf = COLOR_CONFIGS[color]

                # 奇数行の背景を少し明るくして見やすくする（ストライプ効果）
                if i % 2 == 1:
                    cv2.rectangle(info, (15, y - 20), (625, y + 10), (35, 35, 35), -1)

                # 表示用テキストの整形
                dist_text = f"{fs['distance']:.1f} mm" if fs["distance"] is not None else "---"
                ydiff_text = f"{fs['y_diff']:.1f} px" if fs["y_diff"] is not None else "---"

                # 各項目を固定位置に描画
                cv2.putText(info, color,            (col_x[0], y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, c_conf["text_color"], 2)
                cv2.putText(info, fs["source"],     (col_x[1], y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,  (220, 220, 220), 1)
                cv2.putText(info, fs["used_set"],   (col_x[2], y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,  (220, 220, 220), 1)
                cv2.putText(info, dist_text,        (col_x[3], y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
                cv2.putText(info, fs["judge_text"], (col_x[4], y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, fs["judge_color"], 2)
                cv2.putText(info, ydiff_text,       (col_x[5], y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,  (180, 180, 180), 1)

                y += 45

            cv2.line(info, (15, 350), (625, 350), (100, 100, 100), 1)

            # --- Overall（総合判定）強調エリア ---
            # 背景ボックスと枠線
            box_start = (15, 380)
            box_end = (625, 460)
            cv2.rectangle(info, box_start, box_end, (40, 40, 40), -1)
            cv2.rectangle(info, box_start, box_end, overall_color, 2)

            # テキスト
            cv2.putText(info, f"OVERALL:  {overall_text}", (30, 430),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, overall_color, 2)

            # カメラ(左)と情報パネル(右)を横(hstack)に結合
            display = np.hstack((cameras_left, info))
            cv2.imshow("PoseRing Four Camera 3D Target Game", display)

            if show_mask_runtime:
                # マスク表示は確認用なので、メイン画面に収まるよう小さめに並べる。
                # A/Bそれぞれについて、Cam0/Cam1を横に並べ、4色を縦に並べる。
                mask_view_w = 300
                mask_view_h = 140
                mask_set_columns = []

                for set_obj in [set_a, set_b]:
                    color_rows = []

                    for color in COLOR_ORDER:
                        m0 = set_obj.states[color]["mask0"]
                        m1 = set_obj.states[color]["mask1"]

                        if m0 is None or m1 is None:
                            continue

                        m0_bgr = cv2.cvtColor(m0, cv2.COLOR_GRAY2BGR)
                        m1_bgr = cv2.cvtColor(m1, cv2.COLOR_GRAY2BGR)

                        m0_view = cv2.resize(maybe_flip_for_display(m0_bgr), (mask_view_w, mask_view_h))
                        m1_view = cv2.resize(maybe_flip_for_display(m1_bgr), (mask_view_w, mask_view_h))

                        pair = np.hstack((m0_view, m1_view))

                        cv2.rectangle(pair, (0, 0), (pair.shape[1], 22), (0, 0, 0), -1)
                        cv2.putText(
                            pair,
                            f"{set_obj.name} {color}  Cam0 | Cam1",
                            (6, 16),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.42,
                            COLOR_CONFIGS[color]["text_color"],
                            1,
                        )

                        color_rows.append(pair)

                    if color_rows:
                        mask_set_columns.append(np.vstack(color_rows))

                if mask_set_columns:
                    mask_display = np.hstack(mask_set_columns)
                    cv2.imshow("PoseRing Masks", mask_display)
            else:
                try:
                    cv2.destroyWindow("PoseRing Masks")
                except cv2.error:
                    pass

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q") or key == 27:
                break

            if key == ord("m"):
                show_mask_runtime = not show_mask_runtime
                print("マスク表示:", "ON" if show_mask_runtime else "OFF")

            if key == ord("s"):
                saved_a, missing_a = set_a.set_targets_from_current()
                saved_b, missing_b = set_b.set_targets_from_current()

                # 各色がA/Bどちらかに存在するか確認
                missing_both = []
                for color in COLOR_ORDER:
                    a_target = set_a.states[color]["target"]
                    b_target = set_b.states[color]["target"]
                    if a_target is None and b_target is None:
                        missing_both.append(color)

                last_used = {color: None for color in COLOR_ORDER}
                all_inside_start_time = None
                overall_clear = False

                print("======================================")
                print("A/Bの目標座標を保存しました。")
                print("A saved:", saved_a, "| A missing:", missing_a)
                print("B saved:", saved_b, "| B missing:", missing_b)

                if missing_both:
                    print("注意: A/Bどちらにも目標がない色があります:", missing_both)
                    print("この色は判定できないため、もう一度見える位置で s を押してください。")
                else:
                    print("4色すべてについて、AまたはBに目標座標があります。")

                for color in COLOR_ORDER:
                    print(f"[{color}]")
                    print("  A target:", format_vec(set_a.states[color]["target"]))
                    print("  B target:", format_vec(set_b.states[color]["target"]))
                print("======================================")

            if key == ord("c"):
                set_a.reset_targets()
                set_b.reset_targets()
                last_used = {color: None for color in COLOR_ORDER}
                all_inside_start_time = None
                overall_clear = False
                print("目標座標とCLEAR状態をリセットしました。")

            if key == ord("r"):
                set_a.reset_targets()
                set_b.reset_targets()
                last_used = {color: None for color in COLOR_ORDER}
                all_inside_start_time = None
                overall_clear = False
                print("目標座標・最後に使った判定情報・CLEAR状態をすべてリセットしました。")

    finally:
        set_a.release()
        set_b.release()
        cv2.destroyAllWindows()
        print("終了しました。")


if __name__ == "__main__":
    main()
