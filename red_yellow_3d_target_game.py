import cv2
import numpy as np
import time

from calib_utils import resolve_npz

# =========================
# 設定
# =========================
# Leave CALIB_FILE empty to auto-use the latest calibration session,
# or set it manually to override, e.g.:
#   CALIB_FILE = "calibration_images/calib_B_20260506_161557/stereo_calibration_result.npz"
CALIB_FILE = ""

CALIB_FILE = resolve_npz(CALIB_FILE, prefix="calib_")

CAM0_INDEX = 2
CAM1_INDEX = 3

# 赤のHSV範囲（赤は0度付近と180度付近の2つに分かれる）
LOWER_RED_1 = np.array([0, 90, 50])
UPPER_RED_1 = np.array([10, 255, 255])

LOWER_RED_2 = np.array([170, 90, 50])
UPPER_RED_2 = np.array([179, 255, 255])

# 黄色のHSV範囲（照明によって調整が必要）
LOWER_YELLOW = np.array([20, 50, 80])
UPPER_YELLOW = np.array([35, 255, 255])

MIN_AREA_RED = 70
MIN_AREA_YELLOW = 70

DISPLAY_MIRROR = True
SHOW_MASK = False

# 判定設定
CLEAR_DISTANCE_MM = 200.0   # 目標からこの距離以内なら成功範囲
HOLD_TIME_SEC = 2.0         # 成功範囲内にこの秒数キープしたらCLEAR

kernel = np.ones((5, 5), np.uint8)


# =========================
# ユーティリティ
# =========================
def make_red_mask(hsv):
    """赤はHSVのHが0付近と179付近に分かれるため、2つの範囲を合成する"""
    mask1 = cv2.inRange(hsv, LOWER_RED_1, UPPER_RED_1)
    mask2 = cv2.inRange(hsv, LOWER_RED_2, UPPER_RED_2)
    return cv2.bitwise_or(mask1, mask2)


def make_yellow_mask(hsv):
    """黄色用マスク"""
    return cv2.inRange(hsv, LOWER_YELLOW, UPPER_YELLOW)


def detect_color_center(frame, color_name, mask_func, min_area, box_color, center_color):
    """
    指定色の最大領域を検出して中心(cx, cy, area)を返す。
    見つからなければ None を返す。

    戻り値:
        out  : 描画済み画像
        mask : 2値マスク
        res  : (cx, cy, area) または None
        msg  : 表示用文字列
        text_color: 表示用文字色
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    mask = mask_func(hsv)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    out = frame.copy()

    if not contours:
        return out, mask, None, f"{color_name}: not found", (0, 0, 255)

    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)

    if area < min_area:
        return out, mask, None, f"{color_name}: too small area={int(area)}", (0, 0, 255)

    M = cv2.moments(c)
    if M["m00"] == 0:
        return out, mask, None, f"{color_name}: invalid moment", (0, 0, 255)

    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])

    x, y, w, h = cv2.boundingRect(c)
    cv2.rectangle(out, (x, y), (x + w, y + h), box_color, 2)
    cv2.circle(out, (cx, cy), 6, center_color, -1)

    return out, mask, (cx, cy, int(area)), f"{color_name}: ({cx}, {cy}) area={int(area)}", (255, 255, 255)


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


def update_judge(current_relative_3d, target_3d, inside_start_time, is_clear):
    """
    目標座標との距離から判定を更新する。
    """
    if current_relative_3d is None or target_3d is None:
        return None, None, False, 0.0, "NO TARGET", (0, 200, 255)

    distance = float(np.linalg.norm(current_relative_3d - target_3d))

    if distance <= CLEAR_DISTANCE_MM:
        if inside_start_time is None:
            inside_start_time = time.time()

        hold_elapsed = time.time() - inside_start_time

        if hold_elapsed >= HOLD_TIME_SEC:
            is_clear = True

        if is_clear:
            return distance, inside_start_time, is_clear, hold_elapsed, "CLEAR!", (0, 255, 0)
        else:
            return distance, inside_start_time, is_clear, hold_elapsed, f"HOLD {hold_elapsed:.1f}/{HOLD_TIME_SEC:.1f}s", (0, 255, 255)

    inside_start_time = None
    is_clear = False

    if distance <= CLEAR_DISTANCE_MM * 2:
        return distance, inside_start_time, is_clear, 0.0, "CLOSE", (0, 255, 255)

    return distance, inside_start_time, is_clear, 0.0, "FAR", (0, 0, 255)


def draw_text_block(img, lines, x, y, line_height=28, scale=0.65, thickness=2):
    """複数行テキストを描画"""
    for i, (text, color) in enumerate(lines):
        cv2.putText(img, text, (x, y + i * line_height),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness)


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
    raise RuntimeError("カメラ0を開けませんでした。")

if not cap1.isOpened():
    raise RuntimeError("カメラ1を開けませんでした。")

for cap in [cap0, cap1]:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)


print("======================================")
print("Red + Yellow 3D Target Game を開始")
print("q / Esc : 終了")
print("Enter   : 現在の赤マーカー位置を原点(0,0,0)に設定")
print("r       : 原点・目標・CLEAR状態をリセット")
print("t       : 現在の赤マーカー位置を赤ゴールとして登録")
print("y       : 現在の黄色マーカー位置を黄色ゴールとして登録")
print("c       : 赤・黄色ゴールとCLEAR状態をリセット")
print("※ 各色が目標まで100mm以内を2秒キープするとCLEAR")
print("======================================")


# =========================
# 状態変数
# =========================
origin_3d = None

target_red_3d = None       # origin設定後の相対座標で保存
target_yellow_3d = None    # origin設定後の相対座標で保存

red_inside_start_time = None
yellow_inside_start_time = None

red_is_clear = False
yellow_is_clear = False


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

    rect0_guided = draw_horizontal_guides(rect0)
    rect1_guided = draw_horizontal_guides(rect1)

    # ======================================
    # 2) rectified画像上で赤・黄色を検出
    # ======================================
    # まず赤を描画
    out0, red_mask0, red_res0, red_msg0, red_color0 = detect_color_center(
        rect0_guided, "RED", make_red_mask, MIN_AREA_RED, (0, 0, 255), (0, 255, 0)
    )
    out1, red_mask1, red_res1, red_msg1, red_color1 = detect_color_center(
        rect1_guided, "RED", make_red_mask, MIN_AREA_RED, (0, 0, 255), (0, 255, 0)
    )

    # 赤を描画した画像に対して黄色を重ねて描画
    out0, yellow_mask0, yellow_res0, yellow_msg0, yellow_color0 = detect_color_center(
        out0, "YELLOW", make_yellow_mask, MIN_AREA_YELLOW, (0, 255, 255), (255, 0, 255)
    )
    out1, yellow_mask1, yellow_res1, yellow_msg1, yellow_color1 = detect_color_center(
        out1, "YELLOW", make_yellow_mask, MIN_AREA_YELLOW, (0, 255, 255), (255, 0, 255)
    )

    # 3D座標を取得
    red_data = get_marker_3d(red_res0, red_res1, P0, P1)
    yellow_data = get_marker_3d(yellow_res0, yellow_res1, P0, P1)

    red_relative_3d = None
    yellow_relative_3d = None

    if red_data is not None:
        if origin_3d is not None:
            red_relative_3d = red_data["point_3d"] - origin_3d
        else:
            red_relative_3d = red_data["point_3d"].copy()

        cv2.line(out0, (0, red_data["cy0"]), (out0.shape[1] - 1, red_data["cy0"]), (0, 255, 255), 1)
        cv2.line(out1, (0, red_data["cy1"]), (out1.shape[1] - 1, red_data["cy1"]), (0, 255, 255), 1)

    if yellow_data is not None:
        if origin_3d is not None:
            yellow_relative_3d = yellow_data["point_3d"] - origin_3d
        else:
            yellow_relative_3d = yellow_data["point_3d"].copy()

        cv2.line(out0, (0, yellow_data["cy0"]), (out0.shape[1] - 1, yellow_data["cy0"]), (0, 255, 255), 1)
        cv2.line(out1, (0, yellow_data["cy1"]), (out1.shape[1] - 1, yellow_data["cy1"]), (0, 255, 255), 1)

    # ======================================
    # 3) 判定
    # ======================================
    red_distance, red_inside_start_time, red_is_clear, red_hold_elapsed, red_judge_text, red_judge_color = update_judge(
        red_relative_3d, target_red_3d, red_inside_start_time, red_is_clear
    )

    yellow_distance, yellow_inside_start_time, yellow_is_clear, yellow_hold_elapsed, yellow_judge_text, yellow_judge_color = update_judge(
        yellow_relative_3d, target_yellow_3d, yellow_inside_start_time, yellow_is_clear
    )

    # ターゲットが登録されている色だけ判定対象にする
    required_clear = []
    if target_red_3d is not None:
        required_clear.append(red_is_clear)
    if target_yellow_3d is not None:
        required_clear.append(yellow_is_clear)

    all_clear = bool(required_clear) and all(required_clear)

    if all_clear:
        overall_text = "ALL CLEAR!"
        overall_color = (0, 255, 0)
    elif len(required_clear) == 0:
        overall_text = "NO GOALS"
        overall_color = (0, 200, 255)
    else:
        overall_text = "PLAYING"
        overall_color = (0, 255, 255)

    # ======================================
    # 4) 情報表示
    # ======================================
    info = np.zeros((340, out0.shape[1] * 2, 3), dtype=np.uint8)

    cv2.putText(info, "RED + YELLOW TARGET GAME", (20, 35),
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

    # 赤情報
    red_lines = []
    if red_data is None:
        red_lines.append(("RED 3D: not available", (0, 0, 255)))
    else:
        rx, ry, rz = red_relative_3d
        red_lines.append((f"RED REL 3D: X:{rx:.1f}  Y:{ry:.1f}  Z:{rz:.1f}", (255, 255, 255)))
        red_lines.append((f"RED epipolar y diff: {red_data['y_diff']:.2f}px", (255, 200, 0)))

    if target_red_3d is None:
        red_lines.append(("RED Goal: not set  |  t: set RED goal", (0, 200, 255)))
    else:
        tx, ty, tz = target_red_3d
        if red_distance is None:
            red_lines.append((f"RED Goal: ({tx:.1f}, {ty:.1f}, {tz:.1f})  distance: ---  Judge: {red_judge_text}", red_judge_color))
        else:
            red_lines.append((f"RED Goal: ({tx:.1f}, {ty:.1f}, {tz:.1f})  distance: {red_distance:.1f}mm  Judge: {red_judge_text}", red_judge_color))

    draw_text_block(info, red_lines, 20, 110, line_height=28, scale=0.62, thickness=2)

    # 黄色情報
    yellow_lines = []
    if yellow_data is None:
        yellow_lines.append(("YELLOW 3D: not available", (0, 0, 255)))
    else:
        yx, yy, yz = yellow_relative_3d
        yellow_lines.append((f"YELLOW REL 3D: X:{yx:.1f}  Y:{yy:.1f}  Z:{yz:.1f}", (255, 255, 255)))
        yellow_lines.append((f"YELLOW epipolar y diff: {yellow_data['y_diff']:.2f}px", (255, 200, 0)))

    if target_yellow_3d is None:
        yellow_lines.append(("YELLOW Goal: not set  |  y: set YELLOW goal", (0, 200, 255)))
    else:
        tx, ty, tz = target_yellow_3d
        if yellow_distance is None:
            yellow_lines.append((f"YELLOW Goal: ({tx:.1f}, {ty:.1f}, {tz:.1f})  distance: ---  Judge: {yellow_judge_text}", yellow_judge_color))
        else:
            yellow_lines.append((f"YELLOW Goal: ({tx:.1f}, {ty:.1f}, {tz:.1f})  distance: {yellow_distance:.1f}mm  Judge: {yellow_judge_text}", yellow_judge_color))

    draw_text_block(info, yellow_lines, 20, 215, line_height=28, scale=0.62, thickness=2)

    cv2.putText(info, f"Overall: {overall_text}", (760, 305),
                cv2.FONT_HERSHEY_SIMPLEX, 0.95, overall_color, 2)

    # ======================================
    # 5) 表示専用の左右反転とテキスト描画
    # ======================================
    disp0 = maybe_flip_for_display(out0, DISPLAY_MIRROR)
    disp1 = maybe_flip_for_display(out1, DISPLAY_MIRROR)

    # 文字が鏡文字にならないよう、反転後に描画する
    cv2.putText(disp0, red_msg0, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.62, red_color0, 2)
    cv2.putText(disp0, yellow_msg0, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.62, yellow_color0, 2)

    cv2.putText(disp1, red_msg1, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.62, red_color1, 2)
    cv2.putText(disp1, yellow_msg1, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.62, yellow_color1, 2)

    # 画面上にも大きく判定を出す
    cv2.putText(disp0, f"RED: {red_judge_text}", (20, disp0.shape[0] - 55),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, red_judge_color, 2)
    cv2.putText(disp0, f"YELLOW: {yellow_judge_text}", (20, disp0.shape[0] - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, yellow_judge_color, 2)

    if all_clear:
        cv2.putText(disp1, "ALL CLEAR!", (20, disp1.shape[0] - 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, overall_color, 3)

    top = np.hstack((disp0, disp1))
    display = np.vstack((top, info))
    cv2.imshow("Red + Yellow 3D Target Game", display)

    if SHOW_MASK:
        red_mask_vis0 = maybe_flip_for_display(cv2.cvtColor(red_mask0, cv2.COLOR_GRAY2BGR), DISPLAY_MIRROR)
        red_mask_vis1 = maybe_flip_for_display(cv2.cvtColor(red_mask1, cv2.COLOR_GRAY2BGR), DISPLAY_MIRROR)
        yellow_mask_vis0 = maybe_flip_for_display(cv2.cvtColor(yellow_mask0, cv2.COLOR_GRAY2BGR), DISPLAY_MIRROR)
        yellow_mask_vis1 = maybe_flip_for_display(cv2.cvtColor(yellow_mask1, cv2.COLOR_GRAY2BGR), DISPLAY_MIRROR)

        cv2.imshow("Red Masks", np.hstack((red_mask_vis0, red_mask_vis1)))
        cv2.imshow("Yellow Masks", np.hstack((yellow_mask_vis0, yellow_mask_vis1)))

    key = cv2.waitKey(1) & 0xFF

    # q または Esc で終了
    if key == ord("q") or key == 27:
        break

    # Enterキーで現在の赤座標を原点に設定
    if key == 13 or key == 10:
        if red_data is not None:
            origin_3d = red_data["point_3d"].copy()
            target_red_3d = None
            target_yellow_3d = None
            red_inside_start_time = None
            yellow_inside_start_time = None
            red_is_clear = False
            yellow_is_clear = False
            print(f"原点を設定しました: X={origin_3d[0]:.3f}, Y={origin_3d[1]:.3f}, Z={origin_3d[2]:.3f}")
            print("赤・黄色の目標座標はリセットされました。")
        else:
            print("赤マーカーが両カメラで検出されていないため、原点を設定できません。")

    # rキーで原点・目標をすべてリセット
    if key == ord("r"):
        origin_3d = None
        target_red_3d = None
        target_yellow_3d = None
        red_inside_start_time = None
        yellow_inside_start_time = None
        red_is_clear = False
        yellow_is_clear = False
        print("原点設定と全目標座標をリセットしました。")

    # tキーで現在の赤相対座標を赤ゴールに設定
    if key == ord("t"):
        if red_relative_3d is not None:
            target_red_3d = red_relative_3d.copy()
            red_inside_start_time = None
            red_is_clear = False
            print(f"赤ゴールを設定しました: X={target_red_3d[0]:.3f}, Y={target_red_3d[1]:.3f}, Z={target_red_3d[2]:.3f}")
        else:
            print("赤マーカーが両カメラで検出されていないため、赤ゴールを設定できません。")

    # yキーで現在の黄色相対座標を黄色ゴールに設定
    if key == ord("y"):
        if yellow_relative_3d is not None:
            target_yellow_3d = yellow_relative_3d.copy()
            yellow_inside_start_time = None
            yellow_is_clear = False
            print(f"黄色ゴールを設定しました: X={target_yellow_3d[0]:.3f}, Y={target_yellow_3d[1]:.3f}, Z={target_yellow_3d[2]:.3f}")
        else:
            print("黄色マーカーが両カメラで検出されていないため、黄色ゴールを設定できません。")

    # cキーで目標だけリセット
    if key == ord("c"):
        target_red_3d = None
        target_yellow_3d = None
        red_inside_start_time = None
        yellow_inside_start_time = None
        red_is_clear = False
        yellow_is_clear = False
        print("赤・黄色ゴールとCLEAR状態をリセットしました。")

cap0.release()
cap1.release()
cv2.destroyAllWindows()
