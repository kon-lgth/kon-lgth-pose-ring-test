"""
scan_cameras.py
---------------
Run this to find which camera indices OpenCV can open on your machine.
Useful for finding USB cameras and OBS Virtual Camera indices.

Usage:
    python scan_cameras.py
"""

import sys
import cv2

print("=" * 50)
print("  PoseRing — Camera Scanner")
print("=" * 50)
print(f"  OpenCV {cv2.__version__}  |  Python {sys.version.split()[0]}")
print()

found = []
for i in range(12):
    cap = cv2.VideoCapture(i)
    if cap.isOpened():
        w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        ret, frame = cap.read()
        ok  = ret and frame is not None
        print(f"  ✅  index {i:>2}  —  {w}x{h}  frame_readable={ok}")
        found.append(i)
    else:
        print(f"  ❌  index {i:>2}  —  not available")
    cap.release()

print()
print("=" * 50)
if found:
    print(f"  Available indices: {found}")
    if len(found) >= 2:
        print(f"\n  👉 Set in capture_calibration_pairs_B.py:")
        print(f"       CAM0_INDEX = {found[0]}   ← first camera  (usb1 / OBS cam 0)")
        print(f"       CAM1_INDEX = {found[1]}   ← second camera (usb2 / OBS cam 1)")
    else:
        print("\n  ⚠️  Only one camera found.")
        print("  Make sure both USB cameras are plugged in and OBS Virtual Camera is ON.")
else:
    print("  ⚠️  No cameras found.")
    print()
    print("  Possible causes:")
    print("  1. Terminal does not have Camera permission.")
    print("     → System Settings → Privacy & Security → Camera → enable Terminal")
    print("  2. No cameras are physically connected.")
    print("  3. OBS Virtual Camera is not started.")
    print("     → In OBS: Tools → Start Virtual Camera")
print("=" * 50)
