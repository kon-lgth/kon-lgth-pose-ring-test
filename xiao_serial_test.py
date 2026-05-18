import serial
import time

SERIAL_PORT = "COM3"
SERIAL_BAUD = 115200

ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=0.1)
time.sleep(2.0)

print("XIAO connected")

print("LED ON")
ser.write(b"1")
time.sleep(2.0)

print("LED OFF")
ser.write(b"0")
time.sleep(2.0)

ser.close()
print("done")