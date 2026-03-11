# mock_device_ioc.py
from caproto.server import PVGroup, pvproperty, run
import random
import asyncio

class MockBeamline(PVGroup):
    temp_a = pvproperty(value=25.0, name="MOCK:TEMP:A")
    temp_b = pvproperty(value=25.0, name="MOCK:TEMP:B")
    press_a = pvproperty(value=1.0, name="MOCK:PRESSURE:A")

    @temp_a.startup
    async def temp_a(self, instance, async_lib):
        while True:
            # Wiggle the values so you see them move in Phoebus
            await instance.write(value=25.0 + random.uniform(-1, 1))
            await asyncio.sleep(1)

if __name__ == "__main__":
    ioc = MockBeamline(prefix="")
    run(ioc.pvdb)
