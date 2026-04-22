import cv2

cap0 = cv2.VideoCapture(0)
cap1 = cv2.VideoCapture(1, cv2.CAP_MSMF)

if not cap0.isOpened():
    raise RuntimeError("カメラ0を開けませんでした。")

if not cap1.isOpened():
    raise RuntimeError("カメラ1を開けませんでした。")

for cap in [cap0, cap1]:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

while True:
    ret0, frame0 = cap0.read()
    ret1, frame1 = cap1.read()

    if not ret0:
        print("カメラ0の取得失敗")
        break
    if not ret1:
        print("カメラ1の取得失敗")
        break

    frame0 = cv2.flip(frame0, 1)
    frame1 = cv2.flip(frame1, 1)

    cv2.imshow("Camera 0 raw", frame0)
    cv2.imshow("Camera 1 raw", frame1)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q") or key == 27:
        break

cap0.release()
cap1.release()
cv2.destroyAllWindows()