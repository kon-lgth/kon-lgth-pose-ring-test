import socket
import json
import traceback

UDP_IP = "0.0.0.0"
UDP_PORT = 5005

print("======================================")
print("UDP receiver starting...")
print(f"Bind IP   : {UDP_IP}")
print(f"Bind port : {UDP_PORT}")
print("Press Ctrl + C to stop")
print("======================================")

try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))

    print("UDP receiver started successfully.")
    print("Waiting for data...")

    while True:
        data, addr = sock.recvfrom(4096)

        text = data.decode("utf-8", errors="replace")

        print("----------")
        print("From:", addr)
        print("Raw:", text)

        try:
            obj = json.loads(text)
            print("JSON:", obj)
        except json.JSONDecodeError:
            print("Not JSON")

except KeyboardInterrupt:
    print("Stopped by Ctrl + C")

except Exception:
    print("ERROR occurred:")
    traceback.print_exc()

finally:
    input("Press Enter to close...")