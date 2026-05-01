import cv2
import numpy as np

# =========================
# 設定
# =========================
CALIB_FILE = r"calibration_images\calib_20260422_121534\stereo_calibration_result.npz"

CAM0_INDEX = 0   # 例: ノートPC内蔵カメラ or USBカメラ
CAM1_INDEX = 1   # 例: DroidCam / USBカメラ

# 緑のHSV範囲（必要に応じて調整）
LOWER_GREEN = np.array([35, 30, 80])
UPPER_GREEN = np.array([85, 255, 255])

MIN_AREA = 500
DISPLAY_MIRROR = True   # 表示だけ左右反転するか
SHOW_MASK = False       # マスク表示を追加するか

kernel = np.ones((5, 5), np.uint8)


# =========================
# ユーティリティ
# =========================
def detect_green_center(frame):
    """
    緑の最大領域を検出して中心(cx, cy, area)を返す
    見つからなければ None

    戻り値:
        out  : 描画済み画像 (テキストは描画しない)
        mask : 2値マスク
        res  : (cx, cy, area) または None
        msg  : 画面上部に表示するステータス文字列
        color: ステータス文字列の色 (B, G, R)
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    mask = cv2.inRange(hsv, LOWER_GREEN, UPPER_GREEN)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    out = frame.copy()

    if not contours:
        return out, mask, None, "GREEN: not found", (0, 0, 255)

    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)

    if area < MIN_AREA:
        return out, mask, None, f"GREEN: too small area={int(area)}", (0, 0, 255)

    M = cv2.moments(c)
    if M["m00"] == 0:
        return out, mask, None, "GREEN: invalid moment", (0, 0, 255)

    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])

    x, y, w, h = cv2.boundingRect(c)
    cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 0), 2)
    cv2.circle(out, (cx, cy), 6, (0, 0, 255), -1)

    return out, mask, (cx, cy, int(area)), f"GREEN: ({cx}, {cy}) area={int(area)}", (255, 255, 255)


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


# =========================
# キャリブレーション結果読み込み
# =========================
data = np.load(CALIB_FILE)

map0x = data["map0x"]
map0y = data["map0y"]
map1x = data["map1x"]
map1y = data["map1y"]

P0 = data["P0"]   # rectified projection matrix
P1 = data["P1"]   # rectified projection matrix


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
print("Rectified Green 3D 計算を開始")
print("q または Esc で終了")
print("※ カメラ位置はキャリブレーション時から動かさないこと")
print("※ 計算は生画像→remap→検出→triangulate の順で実施")
print("※ 左右反転は表示専用")
print("======================================")

while True:
    ret0, frame0 = cap0.read()
    ret1, frame1 = cap1.read()

    if not ret0 or not ret1:
        print("フレーム取得失敗")
        break

    # ======================================
    # 1) 生画像に対して真っ先に rectification を適用
    #    ※ 計算用の画像には flip をかけないこと
    # ======================================
    rect0 = cv2.remap(frame0, map0x, map0y, cv2.INTER_LINEAR)
    rect1 = cv2.remap(frame1, map1x, map1y, cv2.INTER_LINEAR)

    # ガイド線付き画像をベースに描画
    rect0_guided = draw_horizontal_guides(rect0)
    rect1_guided = draw_horizontal_guides(rect1)

    # ======================================
    # 2) rectified画像上で緑検出
    #    ここで得られる(cx, cy)が三角測量に使う正しい座標
    # ======================================
    out0, mask0, res0, msg0, color0 = detect_green_center(rect0_guided)
    out1, mask1, res1, msg1, color1 = detect_green_center(rect1_guided)

    # 中心が両方で見つかれば対応点を結ぶ補助線を描く
    if res0 is not None and res1 is not None:
        cx0, cy0, area0 = res0
        cx1, cy1, area1 = res1
        cv2.line(out0, (0, cy0), (out0.shape[1] - 1, cy0), (0, 255, 255), 1)
        cv2.line(out1, (0, cy1), (out1.shape[1] - 1, cy1), (0, 255, 255), 1)

    # ======================================
    # 3) 3D計算（rectified座標をそのまま使用）
    # ======================================
    info = np.zeros((180, out0.shape[1] * 2, 3), dtype=np.uint8)

    if res0 is not None:
        cx0, cy0, area0 = res0
        text0 = f"Camera 0 (rectified): x={cx0}, y={cy0}, area={area0}"
    else:
        text0 = "Camera 0 (rectified): not found"

    if res1 is not None:
        cx1, cy1, area1 = res1
        text1 = f"Camera 1 (rectified): x={cx1}, y={cy1}, area={area1}"
    else:
        text1 = "Camera 1 (rectified): not found"

    cv2.putText(info, text0, (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.putText(info, text1, (20, 75),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

    if res0 is not None and res1 is not None:
        # rectified画像上の対応点
        pt0 = np.array([[cx0], [cy0]], dtype=np.float64)
        pt1 = np.array([[cx1], [cy1]], dtype=np.float64)

        # 三角測量
        pts_4d = cv2.triangulatePoints(P0, P1, pt0, pt1)
        pts_3d = pts_4d[:3] / pts_4d[3]
        X, Y, Z = pts_3d.flatten()

        disparity = float(cx0 - cx1)

        text3d = f"3D = X:{X:.1f}  Y:{Y:.1f}  Z:{Z:.1f}"
        text_disp = f"disparity = x0-x1 = {disparity:.2f} px"
        text_yerr = f"epipolar y diff = |y0-y1| = {abs(cy0 - cy1):.2f} px"

        cv2.putText(info, text3d, (20, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.putText(info, text_disp, (20, 155),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 200, 0), 2)
        cv2.putText(info, text_yerr, (520, 155),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 255, 255), 2)
    else:
        cv2.putText(info, "3D = not available", (20, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.putText(info, "disparity = not available", (20, 155),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 200, 0), 2)

    # ======================================
    # 4) 表示専用の左右反転とテキスト描画
    # ======================================
    disp0 = maybe_flip_for_display(out0, DISPLAY_MIRROR)
    disp1 = maybe_flip_for_display(out1, DISPLAY_MIRROR)

    # 文字が鏡文字にならないよう、フリップ後の画像にテキストを描画する
    cv2.putText(disp0, msg0, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color0, 2)
    cv2.putText(disp1, msg1, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color1, 2)

    top = np.hstack((disp0, disp1))
    display = np.vstack((top, info))
    cv2.imshow("Green 3D from Stereo Calibration (Rectified)", display)

    if SHOW_MASK:
        mask_vis0 = maybe_flip_for_display(cv2.cvtColor(mask0, cv2.COLOR_GRAY2BGR), DISPLAY_MIRROR)
        mask_vis1 = maybe_flip_for_display(cv2.cvtColor(mask1, cv2.COLOR_GRAY2BGR), DISPLAY_MIRROR)
        mask_top = np.hstack((mask_vis0, mask_vis1))
        cv2.imshow("Green Masks", mask_top)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q") or key == 27:
        break

cap0.release()
cap1.release()
cv2.destroyAllWindows()
