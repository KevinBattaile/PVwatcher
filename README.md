# PVwatcher

PVwatcher is a highly robust, fault-tolerant EPICS Input/Output Controller (IOC) and dashboard generator built with Python and `caproto`. It actively monitors beamline Process Variables (PVs) against configurable high and low limits, providing real-time visual interlocking status through a dynamically generated Phoebus interface.

## Core Features

* **Dynamic GUI Generation:** Phoebus displays (`.bob` files) are automatically built from a simple YAML configuration file, ensuring the UI always perfectly matches the backend logic.
* **3-State Logic:** Supports independent Row and Master System toggles. Statuses are evaluated as `State 1` (Green/OK), `State 0` (Red/Fault), or `State 2` (Grey/Bypassed).
* **Fault-Tolerant Asynchronous Polling:** Built to survive network drops, disconnected PVs, and data-type mismatches without crashing background tasks.
* **Pure Integer ENUM Handling:** Guarantees absolute memory stability between the Phoebus GUI and the Caproto IOC.

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

All system settings, PV targets, and descriptions are defined in `config.yaml`. 

**Important:** The `prefix` must be wrapped in double quotes so the YAML parser does not misinterpret EPICS separators like `:` or `-`.

```yaml
prefix: "XF:19ID-MONITOR:"

target_pvs:
  "XF19IDC-ES{Rbt:1}LN2:Lvl-I": "Robot Dewar Level"
  "SR:OPS-BI{DCCT:1}I:Real-I": "Ring Current"
```

---

## 2. Generating the Phoebus GUI

To prevent version control conflicts, the final `main.bob` dashboard is intentionally excluded from the repository. **Any time you clone this repository or update `config.yaml`, you must regenerate the dashboard.**

Run the generator script:
```bash
python generate_gui.py
```
This script will read `config.yaml`, inject the specific PV names and descriptions into `row_template.bob`, and output a fresh `main.bob` file perfectly tailored to your current configuration.

---

## 3. Running the IOC

Once the environment is active and the configuration is set, start the IOC:

```bash
python monitor_ioc.py
```

* On startup, the IOC will aggressively read the target PVs to jumpstart the network buffers.
* Live values will be logged to the terminal as they arrive.
* You can now open `main.bob` in Phoebus to interact with the system limits and bypass states.

---

## Repository Structure
* `monitor_ioc.py`: The core Caproto server and logic engine.
* `generate_gui.py`: The Python builder for the Phoebus XML parser.
* `config.yaml`: The single-source-of-truth for PV prefixes and targets.
* `row_template.bob`: The master XML template for individual PV rows.
