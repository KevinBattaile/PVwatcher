# PVwatcher

PVwatcher is a highly robust, fault-tolerant EPICS Input/Output Controller (IOC) and dashboard generator built with Python and `caproto`. It actively monitors beamline Process Variables (PVs) against configurable high and low limits, providing real-time visual interlocking status through a dynamically generated Phoebus interface.

## Core Features

* **Persistent Configuration:** PV limits and default notification settings are hardcoded in a YAML file, ensuring your tuned boundaries survive server reboots.
* **Dynamic GUI Generation:** Phoebus displays (`.bob` files) are automatically built from the configuration file, ensuring the UI always perfectly matches the backend logic.
* **3-State Logic:** Supports independent Row and Master System toggles. Statuses are evaluated as `State 1` (Green/OK), `State 0` (Red/Fault), or `State 2` (Grey/Bypassed).
* **Enriched Asynchronous Alerting:** Built-in Slack webhook and SMTP Email notifications run in background threads to alert users of faults without blocking live EPICS data. Alerts include both the human-readable description and the raw PV name. Includes state-tracking to prevent notification spam.
* **Live Operator UI Routing:** Master alert toggles and 6 pre-allocated email slots allow control room operators to route alerts to current shift staff on the fly without restarting the IOC.

---

## Installation & Setup

It is recommended to run PVwatcher inside an isolated environment.

```bash
# Clone the repository
git clone git@github.com:KevinBattaile/PVwatcher.git
cd PVwatcher

# Create and activate a conda environment
conda create -n pvwatcher python=3.12
conda activate pvwatcher

# Install the required dependencies
pip install -r requirements.txt
```

---

## 1. Configuration (`config.yaml`)

All system settings, PV targets, persistent limits, and alert credentials are defined in `config.yaml`. This file acts as the single source of truth for the IOC's **boot-up state**.

**Important:** The `prefix` must be wrapped in double quotes so the YAML parser does not misinterpret EPICS separators like `:` or `-`.

```yaml
prefix: "XF:19ID-MONITOR:"

target_pvs:
  "XF19IDC-ES{Rbt:1}LN2:Lvl-I":
    desc: "Robot Dewar Level"
    low: 20.0
    high: 85.0
  "SR:OPS-BI{DCCT:1}I:Real-I":
    desc: "Ring Current"
    low: 490.0
    high: 510.0

slack_alerts:
  enabled: true
  webhook_url: "[https://hooks.slack.com/services/YOUR/WEBHOOK/URL](https://hooks.slack.com/services/YOUR/WEBHOOK/URL)"

email_alerts:
  enabled: true
  smtp_server: "smtp.your-facility.gov"
  smtp_port: 25
  sender: "pvwatcher@your-facility.gov"
  recipients:
    - "kbattaile@your-facility.gov"
    - "jules@your-facility.gov"
```

---

## 2. Generating the Phoebus GUI

To prevent version control conflicts, the final `main.bob` dashboard is intentionally excluded from the repository. **Any time you clone this repository or add new PVs to `config.yaml`, you must regenerate the dashboard.**

Run the generator script:
```bash
python generate_gui.py
```
This script will read `config.yaml`, inject the specific PV names and descriptions into `row_template.bob`, and output a fresh `main.bob` file perfectly tailored to your current configuration.

---

## 3. Running the IOC & Operator Usage

Once the environment is active and the configuration is set, start the IOC:

```bash
python monitor_ioc.py
```

### The Notification UI
When the IOC boots, it loads the limits and the primary email recipients from `config.yaml`. Inside the Phoebus GUI (`main.bob`), operators have real-time control over alert routing:
* **Master Toggles:** Slack and Email alerts can be independently disabled across the entire system.
* **Recipient Slots:** The system pre-allocates 6 email slots. Slots 1 and 2 will default to the addresses in `config.yaml`. The remaining slots boot up blank and disabled, allowing shift operators to temporarily type in their own email addresses and enable them for the duration of their shift without needing to edit the YAML or restart the server.

---

## Repository Structure
* `monitor_ioc.py`: The core Caproto server and logic engine.
* `generate_gui.py`: The Python builder for the Phoebus XML parser.
* `config.yaml`: The single-source-of-truth for PV prefixes, limits, and boot defaults.
* `row_template.bob`: The master XML template for individual PV rows.
