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

os.environ['EPICS_CAS_AUTO_BEACON_ADDR_LIST'] = 'no'
os.environ['EPICS_CAS_BEACON_ADDR_LIST'] = '127.0.0.1'

def load_config(config_path='config.yaml'):
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

CONFIG = load_config()
TARGET_PVS = CONFIG.get('target_pvs', {})

# --- ALARM NOTIFICATION THREADS ---
def send_slack_alert(webhook_url, message):
    try:
        payload = {"text": message}
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(webhook_url, data=data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=5.0)
        logger.info("Slack alert sent successfully.")
    except Exception as e:
        logger.error(f"Slack notification failed: {e}")

def send_email_alert(email_cfg, live_recipients, subject, body):
    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = email_cfg.get('sender')
        msg['To'] = ", ".join(live_recipients)

        server = smtplib.SMTP(email_cfg.get('smtp_server'), email_cfg.get('smtp_port', 25))
        server.send_message(msg)
        server.quit()
        logger.info(f"Email sent successfully to {len(live_recipients)} recipients.")
    except Exception as e:
        logger.error(f"Email notification failed: {e}")

# --- CAPROTO LOGIC ---
class RecipientRow(PVGroup):
    address = pvproperty(value="", name=":ADDR", dtype=str, max_length=100)
    enable = pvproperty(value=1, name=":ENABLE", dtype=ChannelType.ENUM, enum_strings=["Disable", "Enable"])

    def __init__(self, prefix, init_address, init_enable, *args, **kwargs):
        super().__init__(prefix=prefix, *args, **kwargs)
        self._init_address = init_address
        self._init_enable = init_enable

    @address.startup
    async def address(self, instance, async_lib):
        await instance.write(self._init_address)

    @enable.startup
    async def enable(self, instance, async_lib):
        await instance.write(self._init_enable)


class PVRow(PVGroup):
    enable = pvproperty(value=1, name=":ENABLE", dtype=ChannelType.ENUM, enum_strings=["Disable", "Enable"])
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

    @low.startup
    async def low(self, instance, async_lib):
        await instance.write(self._init_low)

    @low.putter
    async def low(self, instance, value):
        asyncio.get_running_loop().call_later(0.05, lambda: asyncio.create_task(self.parent.trigger_logic(self.pv_name)))
        return value

    @high.startup
    async def high(self, instance, async_lib):
        await instance.write(self._init_high)

    @high.putter
    async def high(self, instance, value):
        asyncio.get_running_loop().call_later(0.05, lambda: asyncio.create_task(self.parent.trigger_logic(self.pv_name)))
        return value

    @enable.putter
    async def enable(self, instance, value):
        if isinstance(value, bytes): value = value.decode().strip('\x00')
        clean_val = 0 if str(value).upper() in ["0", "DISABLE"] else 1
        asyncio.get_running_loop().call_later(0.05, lambda: asyncio.create_task(self.parent.trigger_logic(self.pv_name)))
        return clean_val


class PVWatcherIOC(PVGroup):
    master_enable = pvproperty(value=1, name="MASTER_ENABLE", dtype=ChannelType.ENUM, enum_strings=["SYSTEM OFF", "SYSTEM ON"])
    summary_status = pvproperty(value=1, name="SUMMARY_STATUS", read_only=True, dtype=int)
    last_update = pvproperty(value="Never", name="LAST_UPDATE", read_only=True, dtype=str)

    # Master Notification Toggles
    slack_enable = pvproperty(value=1, name="SLACK:ENABLE", dtype=ChannelType.ENUM, enum_strings=["Disable", "Enable"])
    slack_status = pvproperty(value=1, name="SLACK:STATUS", read_only=True, dtype=int)
    
    email_enable = pvproperty(value=1, name="EMAIL:ENABLE", dtype=ChannelType.ENUM, enum_strings=["Disable", "Enable"])
    email_status = pvproperty(value=1, name="EMAIL:STATUS", read_only=True, dtype=int)

    def __init__(self, target_pvs, prefix, *args, **kwargs):
        super().__init__(prefix=prefix, *args, **kwargs)
        self.master_prefix = prefix
        self.target_pvs = target_pvs
        self.pv_data = {pv: {"value": None} for pv in target_pvs}
        self.rows = {}
        self.previous_states = {pv: None for pv in target_pvs}
        
        # 1. Initialize the Target PV Rows
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

        # 2. Initialize the 6 Email Recipient Slots
        yaml_emails = CONFIG.get('email_alerts', {}).get('recipients', [])
        self.recipients = []
        for i in range(1, 7):
            addr = yaml_emails[i-1] if i-1 < len(yaml_emails) else ""
            en = 1 if addr else 0
            # Prepend the master prefix so they show up correctly in EPICS
            rec_prefix = f"{self.master_prefix}EMAIL:REC{i}"
            rec_row = RecipientRow(prefix=rec_prefix, init_address=addr, init_enable=en)
            self.pvdb.update(rec_row.pvdb)
            self.recipients.append(rec_row)

        # 3. Setup Master Toggles from YAML
        self._init_slack = 1 if CONFIG.get('slack_alerts', {}).get('enabled') else 0
        self._init_email = 1 if CONFIG.get('email_alerts', {}).get('enabled') else 0

    @slack_enable.startup
    async def slack_enable(self, instance, async_lib):
        await instance.write(self._init_slack)

    @slack_enable.putter
    async def slack_enable(self, instance, value):
        asyncio.get_running_loop().call_later(0.1, lambda: asyncio.create_task(self.update_summary()))
        return value

    @email_enable.startup
    async def email_enable(self, instance, async_lib):
        await instance.write(self._init_email)

    @email_enable.putter
    async def email_enable(self, instance, value):
        asyncio.get_running_loop().call_later(0.1, lambda: asyncio.create_task(self.update_summary()))
        return value

    @master_enable.putter
    async def master_enable(self, instance, value):
        if isinstance(value, bytes): value = value.decode().strip('\x00')
        clean_val = 0 if str(value).upper() in ["0", "OFF", "SYSTEM OFF"] else 1
        async def delayed_trigger():
            await asyncio.sleep(0.05)
            for pv_name in self.target_pvs: await self.trigger_logic(pv_name)
            await self.update_summary()
        asyncio.create_task(delayed_trigger())
        return clean_val

    async def trigger_logic(self, pv_name):
        asyncio.get_running_loop().call_soon(lambda: asyncio.create_task(self.update_logic(pv_name)))

    async def update_logic(self, pv_name):
        row = self.rows[pv_name]
        val = self.pv_data[pv_name]["value"]
        
        out_of_bounds = True
        if val is not None:
            pv_info = self.target_pvs.get(pv_name, {})
            
            # --- Exact Text/State Matching ---
            if isinstance(pv_info, dict) and 'expected' in pv_info:
                expected_val = str(pv_info['expected']).strip().lower()
                
                # Safely decode Caproto byte strings if necessary
                live_val = val
                if isinstance(live_val, bytes):
                    live_val = live_val.decode('utf-8', errors='ignore').strip('\x00')
                
                live_val = str(live_val).strip().lower()
                out_of_bounds = (live_val != expected_val)
                
                # --- NEW DEBUG LINE ---
                logger.info(f"[{pv_name}] MATCH CHECK | Live: '{live_val}' | Expected: '{expected_val}' | Faulted: {out_of_bounds}")
                
            # --- Numerical Bounds Checking ---
            else:
                try:
                    out_of_bounds = not (float(row.low.value) <= float(val) <= float(row.high.value))
                except Exception:
                    out_of_bounds = True

        master_off = self.master_enable.value in [0, "0", "SYSTEM OFF"]
        row_off = row.enable.value in [0, "0", "Disable"]

        if master_off or row_off: new_status = 2
        elif val is None or out_of_bounds: new_status = 0
        else: new_status = 1
            
        old_status = self.previous_states.get(pv_name)
        if old_status is not None and new_status != old_status:
            
            # Extract description for alerts
            pv_info = self.target_pvs.get(pv_name, {})
            desc = pv_info.get('desc', 'Unknown System') if isinstance(pv_info, dict) else str(pv_info)

            alert_msg = None
            subject = None
            
            if new_status == 0:
                subject = f"PVwatcher Alert: {desc} Fault"
                alert_msg = f"🚨 *ALARM:* *{desc}* (`{pv_name}`) is OUT OF BOUNDS. \nLive value: {val}"
            elif new_status == 1 and old_status == 0:
                subject = f"PVwatcher Recovery: {desc} Restored"
                alert_msg = f"✅ *RECOVERY:* *{desc}* (`{pv_name}`) is back within normal limits. \nLive value: {val}"
                
            if alert_msg:
                # 1. Dispatch Slack
                slack_on = self.slack_enable.value in [1, "1", "Enable"]
                slack_cfg = CONFIG.get('slack_alerts', {})
                if slack_on and slack_cfg.get('webhook_url'):
                    asyncio.create_task(asyncio.to_thread(send_slack_alert, slack_cfg['webhook_url'], alert_msg))
                
                # 2. Dispatch Email
                email_on = self.email_enable.value in [1, "1", "Enable"]
                email_cfg = CONFIG.get('email_alerts', {})
                if email_on and email_cfg.get('smtp_server'):
                    live_emails = []
                    for r in self.recipients:
                        if r.enable.value in [1, "1", "Enable"]:
                            addr = str(r.address.value).strip('\x00').strip()
                            if addr: live_emails.append(addr)
                    
                    if live_emails:
                        asyncio.create_task(asyncio.to_thread(send_email_alert, email_cfg, live_emails, subject, alert_msg))

        self.previous_states[pv_name] = new_status
        await row.status.write(new_status)
        await self.update_summary()

    async def update_summary(self):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await self.last_update.write(timestamp)

        # Update Master Notification LEDs
        slack_on = self.slack_enable.value in [1, "1", "Enable"]
        has_webhook = bool(CONFIG.get('slack_alerts', {}).get('webhook_url'))
        await self.slack_status.write(1 if (slack_on and has_webhook) else (2 if not slack_on else 0))

        email_on = self.email_enable.value in [1, "1", "Enable"]
        has_smtp = bool(CONFIG.get('email_alerts', {}).get('smtp_server'))
        await self.email_status.write(1 if (email_on and has_smtp) else (2 if not email_on else 0))

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
        self.polled_pvs = {}
        self.subscriptions = []

        # 1. Establish the connections at boot
        for req_pv_name in self.target_pvs:
            try:
                found = await self.client_ctx.get_pvs(req_pv_name, timeout=2.0)
                pv_obj = found[0]
                
                # Do an initial read to populate the GUI immediately
                init_resp = await pv_obj.read(timeout=1.0)
                self.pv_data[req_pv_name]["value"] = init_resp.data[0]
                await self.update_logic(req_pv_name)
                
                pv_info = self.target_pvs.get(req_pv_name, {})
                
                # 2. Sort into Polled (State/Expected) vs Subscribed (Numerical/Bounds)
                if isinstance(pv_info, dict) and 'expected' in pv_info:
                    # Add to the active polling list
                    self.polled_pvs[req_pv_name] = pv_obj
                    logger.info(f"[{req_pv_name}] Configured for Active Polling (State PV)")
                else:
                    # Setup native Caproto passive subscription
                    def make_callback(name_key):
                        def callback(sub, response):
                            try:
                                self.pv_data[name_key]["value"] = response.data[0]
                                asyncio.get_running_loop().create_task(self.update_logic(name_key))
                            except Exception as e:
                                logger.error(f"Callback error for {name_key}: {e}")
                        return callback

                    sub = pv_obj.subscribe()
                    sub.add_callback(make_callback(req_pv_name))
                    self.subscriptions.append(sub)
                    logger.info(f"[{req_pv_name}] Configured for Passive Subscription (Numeric PV)")
                    
            except Exception as e:
                logger.warning(f"Failed to connect to {req_pv_name}: {e}")
                
        # 3. Start the Active Polling Loop ONLY for the state PVs
        if self.polled_pvs:
            async def poll_pvs():
                while True:
                    await asyncio.sleep(0.5)  # Scan twice a second
                    for pv_name, pv_obj in self.polled_pvs.items():
                        try:
                            resp = await pv_obj.read(timeout=0.5)
                            live_val = resp.data[0]
                            
                            # Only trigger the heavy logic if the physical value actually changed
                            if self.pv_data[pv_name]["value"] != live_val:
                                self.pv_data[pv_name]["value"] = live_val
                                asyncio.create_task(self.update_logic(pv_name))
                                
                        except Exception:
                            # If the network drops, set it to None to instantly trigger a Fault alert
                            if self.pv_data[pv_name]["value"] is not None:
                                self.pv_data[pv_name]["value"] = None
                                asyncio.create_task(self.update_logic(pv_name))

            # Launch the background loop
            asyncio.create_task(poll_pvs())

if __name__ == "__main__":
    if not TARGET_PVS:
        logger.error("No PVs found in config.yaml")
    else:
        custom_prefix = CONFIG.get('prefix', 'MONITOR:')
        ioc = PVWatcherIOC(target_pvs=TARGET_PVS, prefix=custom_prefix)
        logger.info(f"Starting PVwatcher with Prefix: {custom_prefix}")
        run(ioc.pvdb)
