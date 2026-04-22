import cv2
import numpy as np
import os
import glob
import shutil
from dataclasses import dataclass

# =========================
# 設定
# =========================
SESSION_DIR = r"calibration_images\calib_20260422_120927"
CAM0_DIR = os.path.join(SESSION_DIR, "cam0")
CAM1_DIR = os.path.join(SESSION_DIR, "cam1")

PATTERN_SIZE = (9, 6)   # 内側の交点数
SQUARE_SIZE = 26.0      # 1マスの一辺の長さ（mm）

# 何枚ぐらい選ぶか
MIN_SELECTED = 15
MAX_SELECTED = 20
TARGET_SELECTED = 18

# 品質判定の下限（厳しすぎると候補が減るので控えめ）
MIN_AREA_RATIO = 0.02          # チェッカーボード外接矩形の画面占有率の最低値（固定値。厳しすぎる場合は自動緩和あり）
MAX_AREA_RATIO = 0.80          # 近すぎてはみ出し気味を避ける
MAX_SIZE_RATIO_DIFF = 0.60     # 左右カメラで盤面サイズが違いすぎるものを除外
MAX_CENTER_NORM = 0.95         # 端すぎるものを除外（0=中央, 1=対角端）

# 多様性選択の重み
W_SHARPNESS = 0.30
W_AREA = 0.20
W_CENTER = 0.15
W_TILT = 0.15
W_BALANCE = 0.20

# 近すぎる姿勢を避けるためのしきい値
MIN_DESC_DIST = 0.12

# 出力先
OUTPUT_FILE = os.path.join(SESSION_DIR, "stereo_calibration_result_auto_selected.npz")
SELECT_DIR = os.path.join(SESSION_DIR, "selected_pairs")
SELECT_CAM0_DIR = os.path.join(SELECT_DIR, "cam0")
SELECT_CAM1_DIR = os.path.join(SELECT_DIR, "cam1")
REPORT_TXT = os.path.join(SESSION_DIR, "selection_report.txt")
CSV_FILE = os.path.join(SESSION_DIR, "selection_scores.csv")

# =========================
# ユーティリティ
# =========================
criteria = (
    cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
    30,
    0.001
)
flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE

@dataclass
class Candidate:
    f0: str
    f1: str
    basename0: str
    basename1: str
    gray0: np.ndarray
    gray1: np.ndarray
    corners0: np.ndarray
    corners1: np.ndarray
    sharp0: float
    sharp1: float
    area_ratio0: float
    area_ratio1: float
    center_norm0: float
    center_norm1: float
    tilt0: float
    tilt1: float
    size_balance: float
    descriptor: np.ndarray
    score: float = 0.0
    rejected_reason: str = ""


def calc_sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def calc_board_stats(corners: np.ndarray, image_size):
    pts = corners.reshape(-1, 2)
    x_min, y_min = pts.min(axis=0)
    x_max, y_max = pts.max(axis=0)
    w = float(x_max - x_min)
    h = float(y_max - y_min)
    area = w * h

    img_w, img_h = image_size
    area_ratio = area / float(img_w * img_h)

    cx = float((x_min + x_max) * 0.5)
    cy = float((y_min + y_max) * 0.5)

    dx = cx - img_w / 2.0
    dy = cy - img_h / 2.0
    diag_half = np.sqrt((img_w / 2.0) ** 2 + (img_h / 2.0) ** 2)
    center_norm = float(np.sqrt(dx * dx + dy * dy) / diag_half)

    # 1行目方向ベクトルでおおまかな傾きを取得
    row = PATTERN_SIZE[0]
    p0 = pts[0]
    p1 = pts[row - 1]
    ang = np.degrees(np.arctan2(p1[1] - p0[1], p1[0] - p0[0]))
    tilt_abs = abs(float(ang))
    tilt_abs = min(tilt_abs, abs(180.0 - tilt_abs))  # 0~90 付近へ寄せる

    return {
        "bbox_w": w,
        "bbox_h": h,
        "area_ratio": area_ratio,
        "center_norm": center_norm,
        "tilt_abs": tilt_abs,
    }


def normalize(values):
    arr = np.array(values, dtype=np.float64)
    if len(arr) == 0:
        return arr
    vmin = arr.min()
    vmax = arr.max()
    if vmax - vmin < 1e-9:
        return np.ones_like(arr) * 0.5
    return (arr - vmin) / (vmax - vmin)


def ensure_clean_dir(path):
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


# =========================
# チェッカーボードの3D座標を作る
# =========================
objp = np.zeros((PATTERN_SIZE[0] * PATTERN_SIZE[1], 3), np.float32)
objp[:, :2] = np.mgrid[0:PATTERN_SIZE[0], 0:PATTERN_SIZE[1]].T.reshape(-1, 2)
objp *= SQUARE_SIZE

# =========================
# 画像一覧取得
# =========================
images0 = sorted(glob.glob(os.path.join(CAM0_DIR, "*.png")))
images1 = sorted(glob.glob(os.path.join(CAM1_DIR, "*.png")))

if len(images0) == 0 or len(images1) == 0:
    raise RuntimeError("保存画像が見つかりません。SESSION_DIR を確認してください。")
if len(images0) != len(images1):
    raise RuntimeError("cam0 と cam1 の画像枚数が一致していません。")

print("======================================")
print("Stereo calibration with auto selection")
print(f"SESSION_DIR: {SESSION_DIR}")
print(f"cam0 images: {len(images0)}")
print(f"cam1 images: {len(images1)}")
print(f"PATTERN_SIZE: {PATTERN_SIZE}")
print(f"SQUARE_SIZE: {SQUARE_SIZE}")
print("======================================")

candidates = []
rejected = []
image_size = None

# =========================
# 候補収集
# =========================
for f0, f1 in zip(images0, images1):
    img0 = cv2.imread(f0)
    img1 = cv2.imread(f1)
    if img0 is None or img1 is None:
        rejected.append((os.path.basename(f0), "read_error"))
        print(f"SKIP(read): {os.path.basename(f0)} / {os.path.basename(f1)}")
        continue

    gray0 = cv2.cvtColor(img0, cv2.COLOR_BGR2GRAY)
    gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
    ret0, corners0 = cv2.findChessboardCorners(gray0, PATTERN_SIZE, flags)
    ret1, corners1 = cv2.findChessboardCorners(gray1, PATTERN_SIZE, flags)

    if not (ret0 and ret1):
        rejected.append((os.path.basename(f0), f"board_not_found(cam0={ret0}, cam1={ret1})"))
        print(f"SKIP(find): {os.path.basename(f0)} / {os.path.basename(f1)}")
        continue

    corners0 = cv2.cornerSubPix(gray0, corners0, (11, 11), (-1, -1), criteria)
    corners1 = cv2.cornerSubPix(gray1, corners1, (11, 11), (-1, -1), criteria)

    image_size = gray0.shape[::-1]
    stats0 = calc_board_stats(corners0, image_size)
    stats1 = calc_board_stats(corners1, image_size)
    sharp0 = calc_sharpness(gray0)
    sharp1 = calc_sharpness(gray1)

    area_ratio0 = stats0["area_ratio"]
    area_ratio1 = stats1["area_ratio"]
    center_norm0 = stats0["center_norm"]
    center_norm1 = stats1["center_norm"]
    tilt0 = stats0["tilt_abs"]
    tilt1 = stats1["tilt_abs"]

    mean_area = (area_ratio0 + area_ratio1) * 0.5
    size_balance = abs(area_ratio0 - area_ratio1) / max(mean_area, 1e-9)

    # まずは明らかな不良を軽く除外
    reason = ""
    if area_ratio0 < MIN_AREA_RATIO or area_ratio1 < MIN_AREA_RATIO:
        reason = "too_small"
    elif area_ratio0 > MAX_AREA_RATIO or area_ratio1 > MAX_AREA_RATIO:
        reason = "too_large"
    elif center_norm0 > MAX_CENTER_NORM or center_norm1 > MAX_CENTER_NORM:
        reason = "too_edge"
    elif size_balance > MAX_SIZE_RATIO_DIFF:
        reason = "left_right_size_mismatch"

    # descriptor は「位置・大きさ・傾き」の大まかな姿勢特徴
    descriptor = np.array([
        center_norm0,
        center_norm1,
        mean_area,
        (tilt0 + tilt1) * 0.5 / 90.0,
        size_balance,
    ], dtype=np.float64)

    cand = Candidate(
        f0=f0,
        f1=f1,
        basename0=os.path.basename(f0),
        basename1=os.path.basename(f1),
        gray0=gray0,
        gray1=gray1,
        corners0=corners0,
        corners1=corners1,
        sharp0=sharp0,
        sharp1=sharp1,
        area_ratio0=area_ratio0,
        area_ratio1=area_ratio1,
        center_norm0=center_norm0,
        center_norm1=center_norm1,
        tilt0=tilt0,
        tilt1=tilt1,
        size_balance=size_balance,
        descriptor=descriptor,
        rejected_reason=reason,
    )

    if reason:
        rejected.append((cand.basename0, reason))
        print(f"REJECT(pre): {cand.basename0} / {cand.basename1} -> {reason}")
    else:
        candidates.append(cand)
        print(f"CANDIDATE  : {cand.basename0} / {cand.basename1}")

if len(candidates) < MIN_SELECTED:
    raise RuntimeError(
        f"前処理後の候補が少なすぎます: {len(candidates)}。\n"
        "しきい値を少し緩めるか、撮影画像を増やしてください。"
    )

# =========================
# スコア計算
# =========================
sharp_mean = [(c.sharp0 + c.sharp1) * 0.5 for c in candidates]
area_mean = [(c.area_ratio0 + c.area_ratio1) * 0.5 for c in candidates]
center_mean = [1.0 - (c.center_norm0 + c.center_norm1) * 0.5 for c in candidates]  # 小さいほど良いので反転
# 傾きは「正面すぎない・傾きすぎない」をほどよく好む。25度前後を軽く優遇
raw_tilt_pref = []
for c in candidates:
    tilt_mean = (c.tilt0 + c.tilt1) * 0.5
    raw_tilt_pref.append(-abs(tilt_mean - 25.0))
balance_good = [1.0 - c.size_balance / MAX_SIZE_RATIO_DIFF for c in candidates]

n_sharp = normalize(sharp_mean)
n_area = normalize(area_mean)
n_center = normalize(center_mean)
n_tilt = normalize(raw_tilt_pref)
n_balance = normalize(balance_good)

for i, c in enumerate(candidates):
    c.score = (
        W_SHARPNESS * n_sharp[i] +
        W_AREA * n_area[i] +
        W_CENTER * n_center[i] +
        W_TILT * n_tilt[i] +
        W_BALANCE * n_balance[i]
    )

candidates.sort(key=lambda x: x.score, reverse=True)

# =========================
# 多様性を考慮して選択
# =========================
selected = []
left = candidates.copy()

# まず最高得点を1枚
selected.append(left.pop(0))

while left and len(selected) < MAX_SELECTED:
    best_idx = None
    best_value = -1e18

    for i, cand in enumerate(left):
        dists = [np.linalg.norm(cand.descriptor - s.descriptor) for s in selected]
        min_dist = min(dists)

        # 類似姿勢を避けつつ、完全に弾きすぎない
        diversity_bonus = min_dist
        penalty = 0.0
        if min_dist < MIN_DESC_DIST:
            penalty = (MIN_DESC_DIST - min_dist) * 0.8

        value = cand.score + diversity_bonus - penalty
        if value > best_value:
            best_value = value
            best_idx = i

    if best_idx is None:
        break

    picked = left.pop(best_idx)
    selected.append(picked)

# 下限を満たすまで必要ならスコア順で補充
if len(selected) < MIN_SELECTED:
    remaining = [c for c in candidates if c not in selected]
    remaining.sort(key=lambda x: x.score, reverse=True)
    while remaining and len(selected) < MIN_SELECTED:
        selected.append(remaining.pop(0))

# TARGET_SELECTED に近づくよう調整
if len(selected) > TARGET_SELECTED:
    selected = selected[:TARGET_SELECTED]

if len(selected) < MIN_SELECTED:
    raise RuntimeError(f"最終選別後の枚数が不足しています: {len(selected)}")

print("======================================")
print(f"Pre-filter candidates : {len(candidates)}")
print(f"Selected pairs        : {len(selected)}")
print("======================================")

# =========================
# 選抜ペアをコピー & レポート保存
# =========================
ensure_clean_dir(SELECT_CAM0_DIR)
ensure_clean_dir(SELECT_CAM1_DIR)

with open(REPORT_TXT, "w", encoding="utf-8") as f:
    f.write("=== Auto selection report ===\n")
    f.write(f"SESSION_DIR={SESSION_DIR}\n")
    f.write(f"Candidates={len(candidates)}\n")
    f.write(f"Selected={len(selected)}\n\n")
    f.write("[Selected]\n")
    for i, c in enumerate(selected):
        dst0 = os.path.join(SELECT_CAM0_DIR, os.path.basename(c.f0))
        dst1 = os.path.join(SELECT_CAM1_DIR, os.path.basename(c.f1))
        shutil.copy2(c.f0, dst0)
        shutil.copy2(c.f1, dst1)
        line = (
            f"{i:02d}: {c.basename0} | score={c.score:.4f} | "
            f"sharp=({c.sharp0:.1f},{c.sharp1:.1f}) | "
            f"area=({c.area_ratio0:.3f},{c.area_ratio1:.3f}) | "
            f"center=({c.center_norm0:.3f},{c.center_norm1:.3f}) | "
            f"tilt=({c.tilt0:.1f},{c.tilt1:.1f}) | "
            f"balance={c.size_balance:.3f}\n"
        )
        f.write(line)

    f.write("\n[Rejected in pre-filter]\n")
    for name, reason in rejected:
        f.write(f"{name}: {reason}\n")

with open(CSV_FILE, "w", encoding="utf-8") as f:
    f.write("file,score,sharp0,sharp1,area_ratio0,area_ratio1,center_norm0,center_norm1,tilt0,tilt1,size_balance,status\n")
    selected_set = {c.basename0 for c in selected}
    for c in candidates:
        status = "selected" if c.basename0 in selected_set else "not_selected"
        f.write(
            f"{c.basename0},{c.score:.6f},{c.sharp0:.3f},{c.sharp1:.3f},"
            f"{c.area_ratio0:.6f},{c.area_ratio1:.6f},{c.center_norm0:.6f},{c.center_norm1:.6f},"
            f"{c.tilt0:.3f},{c.tilt1:.3f},{c.size_balance:.6f},{status}\n"
        )

# =========================
# 選ばれたペアのみでキャリブレーション
# =========================
objpoints = []
imgpoints0 = []
imgpoints1 = []

for c in selected:
    objpoints.append(objp.copy())
    imgpoints0.append(c.corners0)
    imgpoints1.append(c.corners1)

ret0, K0, dist0, rvecs0, tvecs0 = cv2.calibrateCamera(
    objpoints, imgpoints0, image_size, None, None
)
ret1, K1, dist1, rvecs1, tvecs1 = cv2.calibrateCamera(
    objpoints, imgpoints1, image_size, None, None
)

print("Camera 0 calibration RMS error:", ret0)
print("Camera 1 calibration RMS error:", ret1)

stereo_criteria = (
    cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
    100,
    1e-5
)
stereo_flags = cv2.CALIB_FIX_INTRINSIC

ret_stereo, K0, dist0, K1, dist1, R, T, E, F = cv2.stereoCalibrate(
    objpoints,
    imgpoints0,
    imgpoints1,
    K0,
    dist0,
    K1,
    dist1,
    image_size,
    criteria=stereo_criteria,
    flags=stereo_flags
)

print("======================================")
print("Stereo calibration RMS error:", ret_stereo)
print("======================================")

R0, R1, P0, P1, Q, roi0, roi1 = cv2.stereoRectify(
    K0, dist0,
    K1, dist1,
    image_size,
    R, T,
    alpha=0
)

map0x, map0y = cv2.initUndistortRectifyMap(
    K0, dist0, R0, P0, image_size, cv2.CV_32FC1
)
map1x, map1y = cv2.initUndistortRectifyMap(
    K1, dist1, R1, P1, image_size, cv2.CV_32FC1
)

np.savez(
    OUTPUT_FILE,
    image_size=np.array(image_size),
    pattern_size=np.array(PATTERN_SIZE),
    square_size=np.array(SQUARE_SIZE),
    selected_count=np.array(len(selected)),

    K0=K0,
    dist0=dist0,
    K1=K1,
    dist1=dist1,

    R=R,
    T=T,
    E=E,
    F=F,

    R0=R0,
    R1=R1,
    P0=P0,
    P1=P1,
    Q=Q,

    map0x=map0x,
    map0y=map0y,
    map1x=map1x,
    map1y=map1y,
)

print(f"保存しました: {OUTPUT_FILE}")
print(f"選抜画像コピー先: {SELECT_DIR}")
print(f"選別レポート: {REPORT_TXT}")
print(f"スコアCSV: {CSV_FILE}")

print("\n===== Camera 0 Intrinsic Matrix (K0) =====")
print(K0)
print("\n===== Camera 0 Distortion Coeffs (dist0) =====")
print(dist0.ravel())
print("\n===== Camera 1 Intrinsic Matrix (K1) =====")
print(K1)
print("\n===== Camera 1 Distortion Coeffs (dist1) =====")
print(dist1.ravel())
print("\n===== Rotation (R) =====")
print(R)
print("\n===== Translation (T) =====")
print(T.ravel())
print(f"\nEstimated baseline length = {np.linalg.norm(T):.3f} (same unit as SQUARE_SIZE)")
