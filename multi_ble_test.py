import asyncio
from bleak import BleakScanner, BleakClient

# ======================================
# PoseRing 4台BLE接続テスト
# ======================================
# 目的：
# - PoseRing_RED / YELLOW / BLUE / GREEN に接続できるか確認
# - 0 / 1 / 252 を4台へ送れるか確認
# - 251 をREDだけへ送ってクリア音を確認
#
# Arduino側のUUIDと一致させる
# ======================================

SERVICE_UUID = "19B10000-E8F2-537E-4F6C-D104768A1214"
CHAR_UUID = "19B10001-E8F2-537E-4F6C-D104768A1214"

RING_DEVICES = {
    "RED": "PoseRing_RED",
    "YELLOW": "PoseRing_YELLOW",
    "BLUE": "PoseRing_BLUE",
    "GREEN": "PoseRing_GREEN",
}


class MultiBleTester:
    def __init__(self):
        self.clients = {}

    async def connect_all(self):
        print("======================================")
        print("PoseRing 4 BLE connect test")
        print("Searching devices...")
        print("======================================")

        devices = await BleakScanner.discover(timeout=6.0)

        found = {}
        for d in devices:
            if d.name in RING_DEVICES.values():
                found[d.name] = d

        for color, device_name in RING_DEVICES.items():
            print(f"[{color}] target device name: {device_name}")

            if device_name not in found:
                print(f"  ❌ not found: {device_name}")
                continue

            device = found[device_name]
            print(f"  ✅ found: {device.name} / {device.address}")

            try:
                client = BleakClient(device.address)
                await client.connect()

                if client.is_connected:
                    self.clients[color] = client
                    print(f"  ✅ connected: {color}")
                else:
                    print(f"  ❌ connection failed: {color}")

            except Exception as e:
                print(f"  ❌ error connecting {color}: {e}")

        print("======================================")
        print(f"Connected colors: {list(self.clients.keys())}")
        print("======================================")

    async def send(self, color, value):
        if color not in self.clients:
            print(f"[{color}] not connected")
            return

        client = self.clients[color]

        if not client.is_connected:
            print(f"[{color}] disconnected")
            return

        try:
            value = int(value)
            value = max(0, min(255, value))
            await client.write_gatt_char(CHAR_UUID, bytes([value]), response=True)
            print(f"[SEND] {color} <- {value}")
        except Exception as e:
            print(f"[ERROR] send {color} <- {value}: {e}")

    async def send_all(self, value):
        for color in RING_DEVICES.keys():
            await self.send(color, value)

    async def disconnect_all(self):
        print("Disconnecting...")
        for color, client in self.clients.items():
            try:
                if client.is_connected:
                    await client.disconnect()
                    print(f"  disconnected: {color}")
            except Exception as e:
                print(f"  disconnect error {color}: {e}")


async def main():
    tester = MultiBleTester()
    await tester.connect_all()

    print("")
    print("Commands:")
    print("  0      : all off")
    print("  1      : all white")
    print("  252    : all max own color")
    print("  red251 : RED only clear sound")
    print("  r0/r1/r252 : RED only")
    print("  y0/y1/y252 : YELLOW only")
    print("  b0/b1/b252 : BLUE only")
    print("  g0/g1/g252 : GREEN only")
    print("  q      : quit")
    print("")

    try:
        while True:
            cmd = input("cmd> ").strip().lower()

            if cmd == "q":
                break

            elif cmd == "0":
                await tester.send_all(0)

            elif cmd == "1":
                await tester.send_all(1)

            elif cmd == "252":
                await tester.send_all(252)

            elif cmd == "red251":
                await tester.send("RED", 251)

            elif cmd.startswith("r"):
                await tester.send("RED", cmd[1:])

            elif cmd.startswith("y"):
                await tester.send("YELLOW", cmd[1:])

            elif cmd.startswith("b"):
                await tester.send("BLUE", cmd[1:])

            elif cmd.startswith("g"):
                await tester.send("GREEN", cmd[1:])

            else:
                print("Unknown command")

    finally:
        await tester.send_all(0)
        await tester.disconnect_all()


if __name__ == "__main__":
    asyncio.run(main())