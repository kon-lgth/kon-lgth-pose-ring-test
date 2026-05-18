@echo off
cd /d C:\PoseRingTest

set POSERING_SIMULATION=
set POSERING_BLE_MODE=
set POSERING_ENABLE_BLE=

set POSERING_A_BACKEND=DSHOW
set POSERING_A_CAM0=0
set POSERING_A_CAM1=2

"C:\Users\watar\AppData\Local\Programs\Python\Python313\python.exe" "C:\PoseRingTest\webapp\server.py"

pause