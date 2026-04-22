import cv2

for i in range(5):
    cap = cv2.VideoCapture(i)
    if cap.isOpened():
        ret, frame = cap.read()
        if ret:
            cv2.imshow(f"Camera {i}", frame)
        cap.release()

cv2.waitKey(0)
cv2.destroyAllWindows()