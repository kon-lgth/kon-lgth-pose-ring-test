# PoseRingTest

[日本語版](README.md)

## Overview

This project performs stereo calibration using two cameras and measures the 3D positions of colored markers.

The current version supports 3D coordinate detection for four colored markers: red, yellow, blue, and green. It has also been verified that BLE LED feedback to a XIAO nRF52840 Sense works for the red marker.

As of 2026/05/09, a two-PC setup has also been implemented. In this setup, Set A and Set B are processed on separate laptops, and the 3D coordinates from Set B are sent to the main PC via Wi-Fi / UDP.

---

## Requirements

- Windows (verified)
- Python 3.10+
- USB cameras × 2
- XIAO nRF52840 Sense (when using BLE LED feedback)
- NeoPixel LED Ring
- DFPlayer Mini (for goal sound playback)

---

## Required Libraries

Install the following packages:

```bash
pip install opencv-python numpy
```

If you plan to use BLE communication, install the following package as well:

```bash
pip install bleak
```

---

## BLE LED Receiver Program for XIAO nRF52840 Sense

When using `redlight_ring.py` or `redlight_ring_2pc_main.py`, you must upload `RED_blightness_D.ino` to the XIAO nRF52840 Sense beforehand.

In this sketch, the XIAO operates as a BLE device named `PoseRing_YELLOW`.

The received BLE values are interpreted as follows:

- `0`: LED off
- `1`: White LED while BLE is connected
- `2-255`: Red LED brightness
- `250-255`: Treated as inside the goal area (red blinking + sound playback after 3 seconds)

The built-in LED on the XIAO nRF52840 Sense turns on with `LOW` and off with `HIGH`.

---

## How to Run

### 1. Capture Calibration Image Pairs

```bash
python capture_calibration_pairs.py
```

Calibration image pairs will be saved in the `calibration_images` folder.

The `capture_calibration_pairs.py` script includes the following improvements:

- Saves images only when the checkerboard is detected by both cameras
- Does not save images while the board is moving
- Saves images only after the board has remained still for a certain amount of time

### 2. Stereo Calibration

```bash
python stereo_calibrate_from_saved_pairs.py
```

A `.npz` calibration file will be generated.

### 3. 3D Measurement of Four Colored Markers

```bash
python four_color_3d_target_game.py
```

This program computes the 3D coordinates of the red, yellow, blue, and green markers.

Main features:

- Simultaneously detects four colors: red, yellow, blue, and green
- Calculates the 3D coordinates for each color using stereo calibration results
- Press Enter to set the current red marker position as the origin
- Press `s` to save the current 3D coordinates of the four colors as target positions
- Determines whether each color is within a certain distance from its target position
- Displays CLEAR when all four colors remain within the target range for a certain amount of time
- Uses the last detected 3D coordinate for a short time when a color is temporarily lost

### 4. Red Marker LED Ring + Sound Feedback

```bash
python redlight_ring.py
```

This program detects the red marker. When the red marker enters the designated goal position, the PC sends a BLE signal to the XIAO nRF52840 Sense and activates the LED ring.

The BLE version for the red marker has been successfully verified.

Note: You must upload an Arduino program to the XIAO so that it operates as a BLE device named `PoseRing_YELLOW`.

### 5. Two-PC Wi-Fi / UDP Setup

Run the Set B sender program on the sub PC:

```bash
python sub_bset_udp_sender.py
```

Run the two-PC integrated program on the main PC:

```bash
python redlight_ring_2pc_main.py
```

If `UDP age: 0.xx s` appears in the B_SET area on the main PC, the communication is working successfully.

---

## Parameters to Modify Before Running

### Camera Indices

Camera indices may differ depending on the environment. Modify them as needed.

```python
CAM0_INDEX = 0
CAM1_INDEX = 1
```

For the two-PC version, the Set A camera indices on the main PC are configured as follows:

```python
A_CAM0_INDEX = 1
A_CAM1_INDEX = 2
```

### Session Folder

Specify the folder where calibration images were saved.

```python
SESSION_DIR = "calibration_images/xxxx"
```

### Calibration File

Specify the generated `.npz` calibration file.

```python
CALIB_FILE = "calibration_images/xxxx/stereo_calibration_result.npz"
```

For the two-PC version, configure the following on the main PC:

```python
A_CALIB_FILE = r"calibration_images\xxxx\stereo_calibration_result.npz"
USE_B_SET = True
USE_REMOTE_B_SET = True
REMOTE_B_UDP_IP = "0.0.0.0"
REMOTE_B_UDP_PORT = 5005
```

### Camera Backend

The camera backend must match between calibration and runtime.

In this project, Set A was calibrated using the normal `cv2.VideoCapture(index)` method. Therefore, `redlight_ring_2pc_main.py` must use the following setting:

```python
A_BACKEND = "DEFAULT"
```

If `A_BACKEND = "DSHOW"` is used, the same camera index may open a different physical camera. This can cause the calibration result and the actual camera image to mismatch, resulting in severely distorted rectified images.

---

## Notes

- Do not move the cameras after calibration.
- Capture the checkerboard from various angles and distances.
- Lighting conditions may affect color detection accuracy.
- Set A and Set B are calibrated separately, so their 3D coordinate systems must not be directly mixed.
- If a marker is detected by Set A, it is judged using Set A coordinates. If it is supplemented by Set B, it is judged using Set B coordinates.

---

## Folder Structure

```text
PoseRingTest/
├─ capture_calibration_pairs.py
├─ stereo_calibrate_from_saved_pairs.py
├─ green_3d_from_calibration.py
├─ four_color_3d_target_game.py
├─ redlight_ring.py
├─ redlight_ring_2pc_main.py
├─ sub_bset_udp_sender.py
├─ yellow_3d_ble_led_test.py
├─ xiao_ble_led_receiver.ino
├─ RED_blightness_D.ino
├─ camera_check_2cam.py
├─ camera_index_check.py
├─ calibration_images/
└─ archive/
```

---

## Current Progress

### 2026/05/01

#### Program Improvements

- During calibration, images are not saved while the board is moving
- Pressing `s` saves the current coordinates of all four colors as target positions
- CLEAR is displayed when all four colors are within the target range
- When a color is lost, the last detected coordinate is used for a short time

#### BLE LED Feedback for Yellow Marker

- When the yellow marker enters the goal range, the PC sends a BLE signal to the XIAO nRF52840 Sense
- The built-in LED on the XIAO turns on
- The LED turns off when the yellow marker leaves the goal range

### 2026/05/04

#### Four-Camera Version

A version using two stereo camera sets, for a total of four cameras, was implemented.

```bash
python four_camera_3d_target_game.py
```

- Set A: the main stereo camera pair
- Set B: the backup stereo camera pair used when a marker is lost in Set A

Set A and Set B are calibrated separately. Therefore, their 3D coordinate systems are not directly mixed. The judgment rules are as follows:

1. If a marker is detected by Set A  
   → Compare the current Set A coordinate with the Set A target coordinate

2. If a marker is not detected by Set A but is detected by Set B  
   → Compare the current Set B coordinate with the Set B target coordinate

3. If a marker is detected by neither Set A nor Set B  
   → Use the last used coordinate for a short time

### 2026/05/06

#### Red Marker LED Ring and Sound Feedback

```bash
python redlight_ring.py
```

For the red marker, the program calculates the distance between the current position and the saved target position, and changes the red brightness of the NeoPixel LED ring according to that distance.

Main behavior:

- The LED ring lights up white while BLE is connected
- The LED changes gradually from white to red as the red marker approaches the target
- The PC sends the maximum value, 255, when the red marker enters the goal area
- The XIAO treats values of 250 or higher as being inside the goal area and starts blinking red
- After the marker stays inside the goal area for 3 seconds, a sound effect is played using the DFPlayer Mini
- If the marker leaves the goal area, the 3-second timer is reset

#### Device-Side Firmware for XIAO nRF52840 Sense

```bash
RED_blightness_D.ino
```

The XIAO nRF52840 Sense must be programmed with `RED_blightness_D.ino` before running `redlight_ring.py`.

The Arduino sketch interprets BLE values as follows:

- `0`: LED off
- `1`: White LED while BLE is connected
- `2-255`: Red LED brightness
- `250-255`: Treated as inside the goal area

### 2026/05/09

#### Two-PC Wi-Fi / UDP Setup

A two-PC setup was implemented using Wi-Fi communication. Set A and Set B are processed on separate laptops.

#### System Configuration

Main PC:

- Calculates the 3D coordinates from the two Set A cameras
- Receives the 3D coordinates of Set B from the sub PC via UDP
- Uses Set B coordinates as a backup only when a marker is lost in Set A
- Sends BLE LED feedback to the XIAO nRF52840 Sense

Sub PC:

- Calculates the 3D coordinates from the two Set B cameras
- Sends the coordinate data to the main PC as JSON via Wi-Fi / UDP

#### Files Used

```bash
redlight_ring_2pc_main.py
```

- Two-PC integrated version executed on the main PC
- Handles Set A camera processing, Set B UDP reception, final judgment, and BLE transmission

```bash
sub_bset_udp_sender.py
```

- Set B sender program executed on the sub PC
- Handles Set B camera processing, 3D coordinate calculation, and UDP transmission

#### How to Run

1. Connect both the main PC and the sub PC to the same Wi-Fi network.
2. Run `sub_bset_udp_sender.py` on the sub PC.
3. Run `redlight_ring_2pc_main.py` on the main PC.
4. If `UDP age: 0.xx s` appears in the B_SET area on the main PC, the communication is working successfully.

#### Confirmed Results

- UDP communication from the sub PC to the main PC worked on the university Wi-Fi network
- The main PC successfully received the Set B 3D coordinates from the sub PC
- The main PC prioritized Set A and used Set B coordinates only when a marker was lost in Set A
- BLE LED feedback from the main PC to the XIAO nRF52840 Sense worked together with the two-PC setup
