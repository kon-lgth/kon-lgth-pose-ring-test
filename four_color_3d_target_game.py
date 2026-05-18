import cv2
import numpy as np
import time

# =========================
# 設定
# =========================
CALIB_FILE = r"calibration_images\calib_A_20260506_130215\stereo_calibration_result.npz"

CAM0_INDEX = 4
CAM1_INDEX = 3

DISPLAY_MIRROR = True
SHOW_MASK = False

# 判定設定
CLEAR_DISTANCE_MM = 200.0   # 目標からこの距離以内なら成功範囲
HOLD_TIME_SEC = 2.0         # 4色すべてが成功範囲内にこの秒数入ったら CLEAR

# 色領域の最小面積
MIN_AREA = 70

kernel = np.ones((5, 5), np.uint8)

# =========================
# HSV設定
# 環境の照明によって調整が必要です
# =========================
# 赤はHSVのHが0付近と179付近の2つに分かれる
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


# =========================
# 色設定
# =========================
# box_color, center_color はBGR
COLOR_CONFIGS = {
    "RED": {
        "display_name": "RED",
        "box_color": (0, 0, 255),
        "center_color": (0, 255, 0),
        "text_color": (0, 0, 255),
    },
    "YELLOW": {
        "display_name": "YELLOW",
        "box_color": (0, 255, 255),
        "center_color": (255, 0, 255),
        "text_color": (0, 255, 255),
    },
    "BLUE": {
        "display_name": "BLUE",
        "box_color": (255, 0, 0),
        "center_color": (0, 255, 255),
        "text_color": (255, 120, 0),
    },
    "GREEN": {
        "display_name": "GREEN",
        "box_color": (0, 255, 0),
        "center_color": (0, 0, 255),
        "text_color": (0, 255, 0),
    },
}

COLOR_ORDER = ["RED", "YELLOW", "BLUE", "GREEN"]


# =========================
# マスク作成
# =========================
def make_red_mask(hsv):
    """赤はHSVのHが0付近と179付近に分かれるため、2つの範囲を合成する"""
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
# ユーティリティ
# =========================
def detect_color_center(source_frame, draw_frame, color_name, mask_func, min_area, box_color, center_color):
    """
    source_frame上で指定色の最大領域を検出し、draw_frameに描画する。
    見つかった場合は (cx, cy, area) を返す。

    注意:
        検出はsource_frameで行い、描画はdraw_frameへ行う。
        こうすることで、すでに描いた線や文字が次の色検出に影響しにくくなる。
    """
    hsv = cv2.cvtColor(source_frame, cv2.COLOR_BGR2HSV)

    mask = mask_func(hsv)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return mask, None, f"{color_name}: not found", (0, 0, 255)

    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)

    if area < min_area:
        return mask, None, f"{color_name}: too small area={int(area)}", (0, 0, 255)

    M = cv2.moments(c)
    if M["m00"] == 0:
        return mask, None, f"{color_name}: invalid moment", (0, 0, 255)

    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])

    x, y, w, h = cv2.boundingRect(c)
    cv2.rectangle(draw_frame, (x, y), (x + w, y + h), box_color, 2)
    cv2.circle(draw_frame, (cx, cy), 6, center_color, -1)

    return mask, (cx, cy, int(area)), f"{color_name}: ({cx}, {cy}) area={int(area)}", (255, 255, 255)


def draw_horizontal_guides(img, step=40):
    """整列確認用の横ガイド線を描画"""
    out = img.copy()
    h, w = out.shape[:2]
    for y in range(step, h, step):
        cv2.line(out, (0, y), (w - 1, y), (255, 0, 0), 1)
    return out


def maybe_flip_for_display(img, enable=True):
    """表示専用の左右反転"""
    if enable:
        return cv2.flip(img, 1)
    return img


def triangulate_3d(cx0, cy0, cx1, cy1, P0, P1):
    """rectified画像上の対応点から3D座標を計算"""
    pt0 = np.array([[cx0], [cy0]], dtype=np.float64)
    pt1 = np.array([[cx1], [cy1]], dtype=np.float64)

    pts_4d = cv2.triangulatePoints(P0, P1, pt0, pt1)
    pts_3d = pts_4d[:3] / pts_4d[3]
    return pts_3d.flatten()


def get_marker_3d(res0, res1, P0, P1):
    """
    左右両方でマーカーが見つかった場合に3D座標などを返す。
    見つからなければ None を返す。
    """
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


def draw_text_block(img, lines, x, y, line_height=25, scale=0.55, thickness=2):
    """複数行テキストを描画"""
    for i, (text, color) in enumerate(lines):
        cv2.putText(
            img,
            text,
            (x, y + i * line_height),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            color,
            thickness,
        )


def judge_distance(current_relative_3d, target_3d):
    """
    現在座標と目標座標の距離を計算し、表示用ステータスを返す。
    HOLD/CLEARは4色同時判定で行うので、ここでは色ごとの距離判定だけを行う。
    """
    if target_3d is None:
        return None, False, "NO TARGET", (0, 200, 255)

    if current_relative_3d is None:
        return None, False, "NO CURRENT", (0, 0, 255)

    distance = float(np.linalg.norm(current_relative_3d - target_3d))

    if distance <= CLEAR_DISTANCE_MM:
        return distance, True, "OK", (0, 255, 0)
    if distance <= CLEAR_DISTANCE_MM * 2:
        return distance, False, "CLOSE", (0, 255, 255)
    return distance, False, "FAR", (0, 0, 255)


def format_vec(v):
    if v is None:
        return "---"
    return f"X:{v[0]:.1f} Y:{v[1]:.1f} Z:{v[2]:.1f}"


# =========================
# キャリブレーション結果読み込み
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
cap0 = cv2.VideoCapture(CAM0_INDEX)
cap1 = cv2.VideoCapture(CAM1_INDEX)

if not cap0.isOpened():
    raise RuntimeError("カメラ0を開けませんでした。CAM0_INDEX を確認してください。")

if not cap1.isOpened():
    raise RuntimeError("カメラ1を開けませんでした。CAM1_INDEX を確認してください。")

for cap in [cap0, cap1]:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)


print("======================================")
print("Four Color 3D Target Game を開始")
print("q / Esc : 終了")
print("Enter   : 現在の赤マーカー位置を原点(0,0,0)に設定")
print("s       : 現在の4色3D座標を同時に目標として保存")
print("c       : 4色の目標座標とCLEAR状態をリセット")
print("r       : 原点・目標・CLEAR状態をすべてリセット")
print("※ 色を見失った場合は、最後に検知した3D座標を使用します")
print(f"※ 4色すべてが目標から {CLEAR_DISTANCE_MM:.0f} mm 以内を {HOLD_TIME_SEC:.1f} 秒キープするとCLEAR")
print("======================================")


# =========================
# 状態変数
# =========================
origin_3d = None

states = {}
for name in COLOR_ORDER:
    states[name] = {
        "last_point_3d": None,      # 最後に検知できた生の3D座標
        "last_data": None,          # 最後に検知できた詳細情報
        "current_point_3d": None,   # 今フレームで使用する生の3D座標。LIVEまたはLAST
        "current_relative_3d": None,
        "target_3d": None,          # origin設定後の相対座標で保存
        "source": "NO DATA",       # LIVE / LAST / NO DATA
        "distance": None,
        "inside": False,
        "judge_text": "NO TARGET",
        "judge_color": (0, 200, 255),
        "msg0": f"{name}: not found",
        "msg1": f"{name}: not found",
        "msg_color0": (0, 0, 255),
        "msg_color1": (0, 0, 255),
        "mask0": None,
        "mask1": None,
    }

all_inside_start_time = None
overall_clear = False


while True:
    ret0, frame0 = cap0.read()
    ret1, frame1 = cap1.read()

    if not ret0:
        print("カメラ0のフレーム取得に失敗しました。")
        break

    if not ret1:
        print("カメラ1のフレーム取得に失敗しました。")
        break

    # ======================================
    # 1) 生画像に対して rectification を適用
    # ======================================
    rect0 = cv2.remap(frame0, map0x, map0y, cv2.INTER_LINEAR)
    rect1 = cv2.remap(frame1, map1x, map1y, cv2.INTER_LINEAR)

    # 表示用。検出そのものにはガイド線なしのrect画像を使う
    out0 = draw_horizontal_guides(rect0)
    out1 = draw_horizontal_guides(rect1)

    # ======================================
    # 2) rectified画像上で4色を検出
    # ======================================
    for name in COLOR_ORDER:
        cfg = COLOR_CONFIGS[name]

        mask0, res0, msg0, msg_color0 = detect_color_center(
            rect0,
            out0,
            name,
            MASK_FUNCS[name],
            MIN_AREA,
            cfg["box_color"],
            cfg["center_color"],
        )
        mask1, res1, msg1, msg_color1 = detect_color_center(
            rect1,
            out1,
            name,
            MASK_FUNCS[name],
            MIN_AREA,
            cfg["box_color"],
            cfg["center_color"],
        )

        states[name]["mask0"] = mask0
        states[name]["mask1"] = mask1
        states[name]["msg0"] = msg0
        states[name]["msg1"] = msg1
        states[name]["msg_color0"] = msg_color0
        states[name]["msg_color1"] = msg_color1

        live_data = get_marker_3d(res0, res1, P0, P1)

        if live_data is not None:
            # 両カメラで検出できた場合は、最新座標として保存
            states[name]["last_point_3d"] = live_data["point_3d"].copy()
            states[name]["last_data"] = live_data
            states[name]["current_point_3d"] = live_data["point_3d"].copy()
            states[name]["source"] = "LIVE"

            # 対応点確認用の水平線
            cv2.line(out0, (0, live_data["cy0"]), (out0.shape[1] - 1, live_data["cy0"]), cfg["box_color"], 1)
            cv2.line(out1, (0, live_data["cy1"]), (out1.shape[1] - 1, live_data["cy1"]), cfg["box_color"], 1)
        else:
            # 見失った場合は最後に検知した3D座標を使用
            if states[name]["last_point_3d"] is not None:
                states[name]["current_point_3d"] = states[name]["last_point_3d"].copy()
                states[name]["source"] = "LAST"
            else:
                states[name]["current_point_3d"] = None
                states[name]["source"] = "NO DATA"

        # originが設定されている場合は相対座標にする
        if states[name]["current_point_3d"] is not None:
            if origin_3d is not None:
                states[name]["current_relative_3d"] = states[name]["current_point_3d"] - origin_3d
            else:
                states[name]["current_relative_3d"] = states[name]["current_point_3d"].copy()
        else:
            states[name]["current_relative_3d"] = None

    # ======================================
    # 3) 4色の距離判定
    # ======================================
    all_targets_set = all(states[name]["target_3d"] is not None for name in COLOR_ORDER)

    for name in COLOR_ORDER:
        distance, inside, judge_text, judge_color = judge_distance(
            states[name]["current_relative_3d"],
            states[name]["target_3d"],
        )
        states[name]["distance"] = distance
        states[name]["inside"] = inside
        states[name]["judge_text"] = judge_text
        states[name]["judge_color"] = judge_color

    all_inside = all_targets_set and all(states[name]["inside"] for name in COLOR_ORDER)

    # 4色すべてが同時に範囲内にいる時間を計測
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
    elif not all_targets_set:
        overall_text = "NO 4-COLOR GOAL | s: set 4-color goal"
        overall_color = (0, 200, 255)
    elif all_inside:
        overall_text = f"HOLD {hold_elapsed:.1f}/{HOLD_TIME_SEC:.1f}s"
        overall_color = (0, 255, 255)
    else:
        overall_text = "PLAYING"
        overall_color = (0, 255, 255)

    # ======================================
    # 4) 情報表示
    # ======================================
    info = np.zeros((390, out0.shape[1] * 2, 3), dtype=np.uint8)

    cv2.putText(info, "FOUR COLOR 3D TARGET GAME", (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2)

    # 原点情報
    if origin_3d is None:
        origin_text = "Origin: not set  |  Enter: set RED current position as origin"
        origin_color = (0, 200, 255)
    else:
        ox, oy, oz = origin_3d
        origin_text = f"Origin RAW: ({ox:.1f}, {oy:.1f}, {oz:.1f})  |  r: reset all"
        origin_color = (0, 255, 0)

    cv2.putText(info, origin_text, (20, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, origin_color, 2)

    cv2.putText(info, "s: set 4-color target | c: reset targets | q/Esc: quit | LOST => use LAST 3D point", (20, 100),
                cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2)

    # 色ごとの状態表示
    y_base = 135
    for i, name in enumerate(COLOR_ORDER):
        st = states[name]
        cfg = COLOR_CONFIGS[name]
        x = 20 if i < 2 else 650
        y = y_base + (i % 2) * 105

        lines = []
        lines.append((f"[{name}] Source: {st['source']}", cfg["text_color"]))
        lines.append((f"Current REL 3D: {format_vec(st['current_relative_3d'])}", (255, 255, 255)))

        if st["last_data"] is not None and st["source"] == "LIVE":
            lines.append((f"epipolar y diff: {st['last_data']['y_diff']:.2f}px", (255, 200, 0)))
        else:
            lines.append(("epipolar y diff: ---", (120, 120, 120)))

        if st["target_3d"] is None:
            lines.append(("Goal: not set", (0, 200, 255)))
        else:
            dist_text = "---" if st["distance"] is None else f"{st['distance']:.1f}mm"
            lines.append((f"Goal: {format_vec(st['target_3d'])} | Dist: {dist_text} | {st['judge_text']}", st["judge_color"]))

        draw_text_block(info, lines, x, y, line_height=24, scale=0.53, thickness=2)

    cv2.putText(info, f"Overall: {overall_text}", (650, 360),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, overall_color, 2)

    # ======================================
    # 5) 表示専用の左右反転とテキスト描画
    # ======================================
    disp0 = maybe_flip_for_display(out0, DISPLAY_MIRROR)
    disp1 = maybe_flip_for_display(out1, DISPLAY_MIRROR)

    # 文字が鏡文字にならないよう、反転後に描画する
    text_y = 28
    for name in COLOR_ORDER:
        st = states[name]
        cfg = COLOR_CONFIGS[name]

        cv2.putText(disp0, st["msg0"], (10, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, st["msg_color0"], 2)
        cv2.putText(disp1, st["msg1"], (10, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, st["msg_color1"], 2)
        text_y += 26

    # 画面上にも判定を表示
    judge_y = disp0.shape[0] - 100
    for name in COLOR_ORDER:
        st = states[name]
        label = f"{name}: {st['judge_text']} ({st['source']})"
        cv2.putText(disp0, label, (20, judge_y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, st["judge_color"], 2)
        judge_y += 24

    if overall_clear:
        cv2.putText(disp1, "ALL CLEAR!", (20, disp1.shape[0] - 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, overall_color, 3)
    elif all_targets_set and all_inside:
        cv2.putText(disp1, f"HOLD {hold_elapsed:.1f}/{HOLD_TIME_SEC:.1f}s", (20, disp1.shape[0] - 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, overall_color, 3)

    top = np.hstack((disp0, disp1))
    display = np.vstack((top, info))
    cv2.imshow("Four Color 3D Target Game", display)

    if SHOW_MASK:
        mask_rows = []
        for name in COLOR_ORDER:
            m0 = states[name]["mask0"]
            m1 = states[name]["mask1"]
            if m0 is not None and m1 is not None:
                m0_bgr = cv2.cvtColor(m0, cv2.COLOR_GRAY2BGR)
                m1_bgr = cv2.cvtColor(m1, cv2.COLOR_GRAY2BGR)
                mask_rows.append(np.hstack((maybe_flip_for_display(m0_bgr, DISPLAY_MIRROR), maybe_flip_for_display(m1_bgr, DISPLAY_MIRROR))))
        if mask_rows:
            cv2.imshow("Masks", np.vstack(mask_rows))

    key = cv2.waitKey(1) & 0xFF

    # q または Esc で終了
    if key == ord("q") or key == 27:
        break

    # Enterキーで現在の赤座標を原点に設定
    if key == 13 or key == 10:
        red_point = states["RED"]["current_point_3d"]
        if red_point is not None:
            origin_3d = red_point.copy()
            for name in COLOR_ORDER:
                states[name]["target_3d"] = None
                states[name]["distance"] = None
                states[name]["inside"] = False
            all_inside_start_time = None
            overall_clear = False
            print(f"原点を設定しました: X={origin_3d[0]:.3f}, Y={origin_3d[1]:.3f}, Z={origin_3d[2]:.3f}  source={states['RED']['source']}")
            print("4色の目標座標はリセットされました。")
        else:
            print("赤マーカーの3D座標がないため、原点を設定できません。")

    # sキーで現在の4色相対座標を同時に目標として保存
    if key == ord("s"):
        missing = [name for name in COLOR_ORDER if states[name]["current_relative_3d"] is None]
        if missing:
            print("4色すべての3D座標がそろっていないため、目標を設定できません。")
            print("不足:", ", ".join(missing))
        else:
            for name in COLOR_ORDER:
                states[name]["target_3d"] = states[name]["current_relative_3d"].copy()
                states[name]["distance"] = None
                states[name]["inside"] = False

            all_inside_start_time = None
            overall_clear = False

            print("4色の目標座標を同時に設定しました。")
            for name in COLOR_ORDER:
                target = states[name]["target_3d"]
                src = states[name]["source"]
                print(f"  {name:6s}: X={target[0]:.3f}, Y={target[1]:.3f}, Z={target[2]:.3f}  source={src}")

            if any(states[name]["source"] == "LAST" for name in COLOR_ORDER):
                print("注意: 一部の色は見失い中だったため、最後に検知した座標を目標として保存しました。")

    # cキーで目標だけリセット
    if key == ord("c"):
        for name in COLOR_ORDER:
            states[name]["target_3d"] = None
            states[name]["distance"] = None
            states[name]["inside"] = False
        all_inside_start_time = None
        overall_clear = False
        print("4色の目標座標とCLEAR状態をリセットしました。")

    # rキーで原点・目標をすべてリセット
    if key == ord("r"):
        origin_3d = None
        for name in COLOR_ORDER:
            states[name]["target_3d"] = None
            states[name]["distance"] = None
            states[name]["inside"] = False
        all_inside_start_time = None
        overall_clear = False
        print("原点設定・4色の目標座標・CLEAR状態をリセットしました。")


cap0.release()
cap1.release()
cv2.destroyAllWindows()
