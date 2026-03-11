import asyncio
import logging
import yaml
import os
import datetime
from caproto.server import PVGroup, pvproperty, run
from caproto.asyncio.client import Context
from caproto import ChannelType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# NSLS-II Network Tuning
os.environ['EPICS_CAS_AUTO_BEACON_ADDR_LIST'] = 'no'
os.environ['EPICS_CAS_BEACON_ADDR_LIST'] = '127.0.0.1'

def load_config(config_path='config.yaml'):
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

CONFIG = load_config()
TARGET_PVS = CONFIG.get('target_pvs', [])

class PVRow(PVGroup):
    # Initialize with 1 (Enable) so it starts natively as an integer
    enable = pvproperty(
        value=1, 
        name=":ENABLE", 
        dtype=ChannelType.ENUM,
        enum_strings=["Disable", "Enable"]
    )
    low = pvproperty(value=-1e9, name=":LOW", dtype=float)
    high = pvproperty(value=1e9, name=":HIGH", dtype=float)
    status = pvproperty(value=1, name=":STATUS", dtype=int, read_only=True)

    def __init__(self, pv_name, parent, *args, **kwargs):
        escaped = pv_name.replace('{', '{{').replace('}', '}}')
        super().__init__(prefix=escaped, *args, **kwargs)
        self.pv_name = pv_name
        self.parent = parent

    @enable.putter
    async def enable(self, instance, value):
        # Cleanly force whatever we receive into the integer index 0 or 1
        if isinstance(value, bytes):
            value = value.decode().strip('\x00')
        
        if str(value).upper() in ["0", "DISABLE"]:
            clean_val = 0
        else:
            clean_val = 1
            
        async def delayed_trigger():
            await asyncio.sleep(0.05)
            await self.parent.trigger_logic(self.pv_name)
        asyncio.create_task(delayed_trigger())
        
        # Return the raw integer to keep Caproto's memory perfect
        return clean_val

    @low.putter
    async def low(self, instance, value):
        async def delayed_trigger():
            await asyncio.sleep(0.05)
            await self.parent.trigger_logic(self.pv_name)
        asyncio.create_task(delayed_trigger())
        return value

    @high.putter
    async def high(self, instance, value):
        async def delayed_trigger():
            await asyncio.sleep(0.05)
            await self.parent.trigger_logic(self.pv_name)
        asyncio.create_task(delayed_trigger())
        return value

class PVWatcherIOC(PVGroup):
    # Initialize with 1 (SYSTEM ON)
    master_enable = pvproperty(
        value=1, 
        name="MASTER_ENABLE", 
        dtype=ChannelType.ENUM,
        enum_strings=["SYSTEM OFF", "SYSTEM ON"]
    )
    summary_status = pvproperty(value=1, name="SUMMARY_STATUS", read_only=True, dtype=int)
    last_update = pvproperty(value="Never", name="LAST_UPDATE", dtype=str, read_only=True)

    def __init__(self, target_pvs, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_pvs = target_pvs
        self.pv_data = {pv: {"value": None} for pv in target_pvs}
        self.rows = {}
        
        for pv in target_pvs:
            row = PVRow(pv_name=pv, parent=self)
            self.rows[pv] = row
            self.pvdb.update(row.pvdb)

    @master_enable.putter
    async def master_enable(self, instance, value):
        if isinstance(value, bytes):
            value = value.decode().strip('\x00')
            
        if str(value).upper() in ["0", "OFF", "SYSTEM OFF"]:
            clean_val = 0
        else:
            clean_val = 1
            
        async def delayed_trigger():
            await asyncio.sleep(0.05)
            for pv_name in self.target_pvs:
                await self.trigger_logic(pv_name)
            await self.update_summary()
        asyncio.create_task(delayed_trigger())
        
        return clean_val

    async def trigger_logic(self, pv_name):
        asyncio.get_running_loop().call_soon(
            lambda: asyncio.create_task(self.update_logic(pv_name))
        )

    async def update_logic(self, pv_name):
        row = self.rows[pv_name]
        val = self.pv_data[pv_name]["value"]
        
        # 1. Math Evaluation (Bulletproof floats)
        out_of_bounds = True
        if val is not None:
            try:
                num_val = float(val)
                out_of_bounds = not (float(row.low.value) <= num_val <= float(row.high.value))
            except Exception as e:
                logger.error(f"Math Error on {pv_name}: {e}")
                out_of_bounds = True

        # 2. Check both strings AND integers to never get fooled by ENUMs again
        master_off = self.master_enable.value in [0, "0", "SYSTEM OFF"]
        row_off = row.enable.value in [0, "0", "Disable"]

        # 3. Apply the 3-State Logic
        if master_off or row_off:
            new_status = 2  # State 2: Grey (Bypassed)
        elif val is None or out_of_bounds:
            new_status = 0  # State 0: Red (Fault)
        else:
            new_status = 1  # State 1: Green (OK)
        
        await row.status.write(new_status)
        await self.update_summary()

    async def update_summary(self):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await self.last_update.write(timestamp)

        master_off = self.master_enable.value in [0, "0", "SYSTEM OFF"]
        
        if master_off:
            await self.summary_status.write(2)
            return
        
        overall = 1
        for pv_name, row in self.rows.items():
            row_on = row.enable.value in [1, "1", "Enable"]
            
            # ONLY check rows that are actively Enabled
            if row_on:
                val = self.pv_data[pv_name]["value"]
                out_of_bounds = True
                
                if val is not None:
                    try:
                        out_of_bounds = not (float(row.low.value) <= float(val) <= float(row.high.value))
                    except Exception:
                        out_of_bounds = True

                # Trip the master if data is missing or out of bounds
                if val is None or out_of_bounds:
                    overall = 0
                    break
                    
        await self.summary_status.write(overall)

    @summary_status.startup
    async def summary_status(self, instance, async_lib):
        self.client_ctx = Context()
        self.subscriptions = []

        for req_pv_name in self.target_pvs:
            try:
                found = await self.client_ctx.get_pvs(req_pv_name, timeout=2.0)
                pv_obj = found[0]
                
                # A closure function guarantees we map the callback to the EXACT dictionary key
                def make_callback(name_key):
                    def callback(sub, response):
                        try:
                            val = response.data[0]
                            logger.info(f"[{name_key}] Live Update Received: {val}")
                            self.pv_data[name_key]["value"] = val
                            asyncio.get_running_loop().create_task(self.update_logic(name_key))
                        except Exception as e:
                            logger.error(f"Callback error for {name_key}: {e}")
                    return callback

                sub = pv_obj.subscribe()
                sub.add_callback(make_callback(req_pv_name))
                self.subscriptions.append(sub)
                
                # >>> THE MAGIC FIX: Force an initial read to jumpstart the network buffer <<<
                init_resp = await pv_obj.read()
                val = init_resp.data[0]
                self.pv_data[req_pv_name]["value"] = val
                logger.info(f"[{req_pv_name}] Initial read successful: {val}")
                
            except Exception as e:
                logger.warning(f"Failed to connect or read {req_pv_name}: {e}")
                
        # Force a full logic evaluation across the board on startup
        for pv_name in self.target_pvs:
            await self.update_logic(pv_name)


if __name__ == "__main__":
    if not TARGET_PVS:
        logger.error("No PVs found in config.yaml")
    else:
        # Grab the custom prefix from your config file, default to 'MONITOR:' if missing
        custom_prefix = CONFIG.get('prefix', 'MONITOR:')

        # If TARGET_PVS is now a dictionary (for descriptions), just pass the keys
        target_list = list(TARGET_PVS.keys()) if isinstance(TARGET_PVS, dict) else TARGET_PVS

        ioc = PVWatcherIOC(target_pvs=target_list, prefix=custom_prefix)
        logger.info(f"Starting PVwatcher with Prefix: {custom_prefix}")
        run(ioc.pvdb)
