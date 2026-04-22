import cv2
import numpy as np
import os
import glob

# =========================
# 設定
# =========================
SESSION_DIR = r"calibration_images\calib_20260422_121534"
CAM0_DIR = os.path.join(SESSION_DIR, "cam0")
CAM1_DIR = os.path.join(SESSION_DIR, "cam1")

PATTERN_SIZE = (9, 6)   # 内側の交点数
SQUARE_SIZE = 26.0      # 1マスの一辺の長さ（mm）。自分の印刷物に合わせて変更する

# 保存先
OUTPUT_FILE = os.path.join(SESSION_DIR, "stereo_calibration_result.npz")

# =========================
# チェッカーボードの3D座標を作る
# =========================
# 例: (0,0,0), (25,0,0), (50,0,0) ... のように並べる
objp = np.zeros((PATTERN_SIZE[0] * PATTERN_SIZE[1], 3), np.float32)
objp[:, :2] = np.mgrid[0:PATTERN_SIZE[0], 0:PATTERN_SIZE[1]].T.reshape(-1, 2)
objp *= SQUARE_SIZE

# 2台分の対応データ
objpoints = []   # 3D座標
imgpoints0 = []  # カメラ0の2D座標
imgpoints1 = []  # カメラ1の2D座標

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
print("Stereo calibration start")
print(f"SESSION_DIR: {SESSION_DIR}")
print(f"cam0 images: {len(images0)}")
print(f"cam1 images: {len(images1)}")
print(f"PATTERN_SIZE: {PATTERN_SIZE}")
print(f"SQUARE_SIZE: {SQUARE_SIZE}")
print("======================================")

criteria = (
    cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
    30,
    0.001
)

flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE

image_size = None
valid_count = 0

# =========================
# 角点検出
# =========================
for f0, f1 in zip(images0, images1):
    img0 = cv2.imread(f0)
    img1 = cv2.imread(f1)

    if img0 is None or img1 is None:
        print(f"読み込み失敗: {f0} or {f1}")
        continue

    gray0 = cv2.cvtColor(img0, cv2.COLOR_BGR2GRAY)
    gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)

    ret0, corners0 = cv2.findChessboardCorners(gray0, PATTERN_SIZE, flags)
    ret1, corners1 = cv2.findChessboardCorners(gray1, PATTERN_SIZE, flags)

    if ret0 and ret1:
        corners0 = cv2.cornerSubPix(
            gray0, corners0, (11, 11), (-1, -1), criteria
        )
        corners1 = cv2.cornerSubPix(
            gray1, corners1, (11, 11), (-1, -1), criteria
        )

        objpoints.append(objp.copy())
        imgpoints0.append(corners0)
        imgpoints1.append(corners1)

        image_size = gray0.shape[::-1]
        valid_count += 1
        print(f"OK   : {os.path.basename(f0)} / {os.path.basename(f1)}")
    else:
        print(f"SKIP : {os.path.basename(f0)} / {os.path.basename(f1)}  "
              f"(cam0={ret0}, cam1={ret1})")

if valid_count < 8:
    raise RuntimeError(
        f"有効ペア数が少なすぎます: {valid_count}。\n"
        "最低でも 8〜10 ペア以上、できれば 15〜20 ペア以上ほしいです。"
    )

print("======================================")
print(f"Valid pairs: {valid_count}")
print("======================================")

# =========================
# 各カメラ単独キャリブレーション
# =========================
ret0, K0, dist0, rvecs0, tvecs0 = cv2.calibrateCamera(
    objpoints, imgpoints0, image_size, None, None
)

ret1, K1, dist1, rvecs1, tvecs1 = cv2.calibrateCamera(
    objpoints, imgpoints1, image_size, None, None
)

print("Camera 0 calibration RMS error:", ret0)
print("Camera 1 calibration RMS error:", ret1)

# =========================
# ステレオキャリブレーション
# =========================
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

# =========================
# Rectification（後で3D計算に使う）
# =========================
R0, R1, P0, P1, Q, roi0, roi1 = cv2.stereoRectify(
    K0, dist0,
    K1, dist1,
    image_size,
    R, T,
    alpha=0
)

# 歪み補正マップ作成
map0x, map0y = cv2.initUndistortRectifyMap(
    K0, dist0, R0, P0, image_size, cv2.CV_32FC1
)
map1x, map1y = cv2.initUndistortRectifyMap(
    K1, dist1, R1, P1, image_size, cv2.CV_32FC1
)

# =========================
# 結果保存
# =========================
np.savez(
    OUTPUT_FILE,
    image_size=np.array(image_size),
    pattern_size=np.array(PATTERN_SIZE),
    square_size=np.array(SQUARE_SIZE),

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
    map1y=map1y
)

print(f"保存しました: {OUTPUT_FILE}")

# =========================
# 結果を見やすく表示
# =========================
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

baseline = np.linalg.norm(T)
print(f"\nEstimated baseline length = {baseline:.3f} (same unit as SQUARE_SIZE)")