import asyncio
from bleak import BleakScanner, BleakClient

DEVICE_NAME = "PoseRing_YELLOW"
LED_CHAR_UUID = "19B10001-E8F2-537E-4F6C-D104768A1214"


async def main():
    print("BLEデバイスを探しています...")

    devices = await BleakScanner.discover(timeout=8.0)

    target = None
    for d in devices:
        print(d.name, d.address)
        if d.name == DEVICE_NAME:
            target = d
            break

    if target is None:
        print("XIAOが見つかりませんでした。")
        print("LightBlueでPoseRing_YELLOWが見えるか、スマホで接続中でないかを確認してください。")
        return

    print(f"接続します: {target.name} / {target.address}")

    async with BleakClient(target.address) as client:
        print("接続成功")

        print("LED ON")
        await client.write_gatt_char(LED_CHAR_UUID, bytes([1]))
        await asyncio.sleep(2)

        print("LED OFF")
        await client.write_gatt_char(LED_CHAR_UUID, bytes([0]))
        await asyncio.sleep(2)

    print("終了")


asyncio.run(main())