import asyncio
import logging
import yaml
import os
import datetime
import json
import urllib.request
import smtplib
from email.message import EmailMessage
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
TARGET_PVS = CONFIG.get('target_pvs', {})

# --- ALARM NOTIFICATION THREADS ---
def send_slack_alert(webhook_url, message):
    """Runs in a background thread to prevent blocking the IOC"""
    try:
        payload = {"text": message}
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(webhook_url, data=data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=5.0)
        logger.info("Slack alert sent successfully.")
    except Exception as e:
        logger.error(f"Slack notification failed: {e}")

def send_email_alert(email_cfg, subject, body):
    """Runs in a background thread to prevent blocking the IOC"""
    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = email_cfg.get('sender')
        msg['To'] = ", ".join(email_cfg.get('recipients', []))

        server = smtplib.SMTP(email_cfg.get('smtp_server'), email_cfg.get('smtp_port', 25))
        server.send_message(msg)
        server.quit()
        logger.info("Email alert sent successfully.")
    except Exception as e:
        logger.error(f"Email notification failed: {e}")

# --- CAPROTO LOGIC ---
class PVRow(PVGroup):
    enable = pvproperty(
        value=1, 
        name=":ENABLE", 
        dtype=ChannelType.ENUM,
        enum_strings=["Disable", "Enable"]
    )
    low = pvproperty(value=-1e9, name=":LOW", dtype=float)
    high = pvproperty(value=1e9, name=":HIGH", dtype=float)
    status = pvproperty(value=1, name=":STATUS", dtype=int, read_only=True)

    def __init__(self, pv_name, parent, low_limit, high_limit, *args, **kwargs):
        escaped = pv_name.replace('{', '{{').replace('}', '}}')
        super().__init__(prefix=escaped, *args, **kwargs)
        self.pv_name = pv_name
        self.parent = parent
        self._init_low = low_limit
        self._init_high = high_limit

    # --- LOW PROPERTY HOOKS ---
    @low.startup
    async def low(self, instance, async_lib):
        await instance.write(self._init_low)

    @low.putter
    async def low(self, instance, value):
        async def delayed_trigger():
            await asyncio.sleep(0.05)
            await self.parent.trigger_logic(self.pv_name)
        asyncio.create_task(delayed_trigger())
        return value

    # --- HIGH PROPERTY HOOKS ---
    @high.startup
    async def high(self, instance, async_lib):
        await instance.write(self._init_high)

    @high.putter
    async def high(self, instance, value):
        async def delayed_trigger():
            await asyncio.sleep(0.05)
            await self.parent.trigger_logic(self.pv_name)
        asyncio.create_task(delayed_trigger())
        return value

    # --- ENABLE PROPERTY HOOKS ---
    @enable.putter
    async def enable(self, instance, value):
        if isinstance(value, bytes):
            value = value.decode().strip('\x00')
        clean_val = 0 if str(value).upper() in ["0", "DISABLE"] else 1
            
        async def delayed_trigger():
            await asyncio.sleep(0.05)
            await self.parent.trigger_logic(self.pv_name)
        asyncio.create_task(delayed_trigger())
        return clean_val

class PVWatcherIOC(PVGroup):
    master_enable = pvproperty(
        value=1, 
        name="MASTER_ENABLE", 
        dtype=ChannelType.ENUM,
        enum_strings=["SYSTEM OFF", "SYSTEM ON"]
    )
    summary_status = pvproperty(value=1, name="SUMMARY_STATUS", read_only=True, dtype=int)
    last_update = pvproperty(value="Never", name="LAST_UPDATE", read_only=True, dtype=str)

    def __init__(self, target_pvs, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_pvs = target_pvs
        self.pv_data = {pv: {"value": None} for pv in target_pvs}
        self.rows = {}
        
        # State tracker to prevent notification spam
        self.previous_states = {pv: None for pv in target_pvs}
        
        for pv in target_pvs:
            pv_info = target_pvs[pv]

            if isinstance(pv_info, dict):
                init_low = float(pv_info.get('low', -1e9))
                init_high = float(pv_info.get('high', 1e9))
            else:
                init_low, init_high = -1e9, 1e9

            row = PVRow(pv_name=pv, parent=self, low_limit=init_low, high_limit=init_high)
            self.rows[pv] = row
            self.pvdb.update(row.pvdb)

    @master_enable.putter
    async def master_enable(self, instance, value):
        if isinstance(value, bytes):
            value = value.decode().strip('\x00')
        clean_val = 0 if str(value).upper() in ["0", "OFF", "SYSTEM OFF"] else 1
            
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
        
        out_of_bounds = True
        if val is not None:
            try:
                num_val = float(val)
                out_of_bounds = not (float(row.low.value) <= num_val <= float(row.high.value))
            except Exception as e:
                logger.error(f"Math Error on {pv_name}: {e}")
                out_of_bounds = True

        master_off = self.master_enable.value in [0, "0", "SYSTEM OFF"]
        row_off = row.enable.value in [0, "0", "Disable"]

        if master_off or row_off:
            new_status = 2  # Grey
        elif val is None or out_of_bounds:
            new_status = 0  # Red
        else:
            new_status = 1  # Green
            
        # --- ALERT TRIGGER LOGIC ---
        old_status = self.previous_states.get(pv_name)
        
        # Only alert if the state actually changed (and ignore the very first boot-up evaluation)
        if old_status is not None and new_status != old_status:
            alert_msg = None
            subject = None
            
            if new_status == 0:
                subject = f"PVwatcher Alert: {pv_name} Fault"
                alert_msg = f"🚨 *ALARM:* `{pv_name}` is OUT OF BOUNDS. \nLive value: {val}"
            elif new_status == 1 and old_status == 0:
                subject = f"PVwatcher Recovery: {pv_name} Restored"
                alert_msg = f"✅ *RECOVERY:* `{pv_name}` is back within normal limits. \nLive value: {val}"
                
            if alert_msg:
                # 1. Dispatch Slack
                slack_cfg = CONFIG.get('slack_alerts', {})
                if slack_cfg.get('enabled') and slack_cfg.get('webhook_url'):
                    asyncio.create_task(asyncio.to_thread(send_slack_alert, slack_cfg['webhook_url'], alert_msg))
                
                # 2. Dispatch Email
                email_cfg = CONFIG.get('email_alerts', {})
                if email_cfg.get('enabled') and email_cfg.get('smtp_server'):
                    asyncio.create_task(asyncio.to_thread(send_email_alert, email_cfg, subject, alert_msg))

        # Update the memory bank
        self.previous_states[pv_name] = new_status
        
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
            if row_on:
                val = self.pv_data[pv_name]["value"]
                out_of_bounds = True
                if val is not None:
                    try:
                        out_of_bounds = not (float(row.low.value) <= float(val) <= float(row.high.value))
                    except Exception:
                        out_of_bounds = True

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
                
                def make_callback(name_key):
                    def callback(sub, response):
                        try:
                            val = response.data[0]
                            # Only uncomment this if you need to debug live network flow
                            # logger.info(f"[{name_key}] Live Update Received: {val}")
                            self.pv_data[name_key]["value"] = val
                            asyncio.get_running_loop().create_task(self.update_logic(name_key))
                        except Exception as e:
                            logger.error(f"Callback error for {name_key}: {e}")
                    return callback

                sub = pv_obj.subscribe()
                sub.add_callback(make_callback(req_pv_name))
                self.subscriptions.append(sub)
                
                init_resp = await pv_obj.read()
                val = init_resp.data[0]
                self.pv_data[req_pv_name]["value"] = val
                logger.info(f"[{req_pv_name}] Initial read successful: {val}")
                
            except Exception as e:
                logger.warning(f"Failed to connect or read {req_pv_name}: {e}")
                
        for pv_name in self.target_pvs:
            await self.update_logic(pv_name)

if __name__ == "__main__":
    if not TARGET_PVS:
        logger.error("No PVs found in config.yaml")
    else:
        custom_prefix = CONFIG.get('prefix', 'MONITOR:')
        target_list = list(TARGET_PVS.keys()) if isinstance(TARGET_PVS, dict) else TARGET_PVS
        
        ioc = PVWatcherIOC(target_pvs=TARGET_PVS, prefix=custom_prefix)
        logger.info(f"Starting PVwatcher with Prefix: {custom_prefix}")
        run(ioc.pvdb)
