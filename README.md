# PVWatcher

A robust EPICS IOC for monitoring external PVs and setting alarms.

## Features

- **Dynamic Configuration**: Loads target PVs from `config.yaml`.
- **Fail-Safe Monitoring**: Monitors external PVs and sets `SUMMARY_STATUS` to 0 (Alarm) if any value is out of bounds or disconnected.
- **Master Control**: `MONITOR:MASTER_ENABLE` allows global enabling/disabling of the monitoring logic.
- **Python 3.6 Compatibility**: Uses `asyncio.ensure_future` and standard Python 3.6 features.
- **Caproto Based**: Uses `caproto` server and async client.

## Requirements

- Python 3.6+
- caproto
- pyyaml

Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

1. **Configure**: Edit `config.yaml` to list the PVs you want to monitor.
2. **Run**:
   ```bash
   python3 monitor_ioc.py --list-pvs
   ```
3. **Control**:
   - `[TARGET]:ENABLE` (1/0): Enable/Disable monitoring for specific PV.
   - `[TARGET]:LOW` / `[TARGET]:HIGH`: Set bounds.
   - `MONITOR:MASTER_ENABLE` (1/0): Master switch.

## PVs Provided

- `MONITOR:MASTER_ENABLE` (Binary)
- `MONITOR:SUMMARY_STATUS` (Binary, 1=OK, 0=ALARM)
- For each target `MOCK:TEMP:A`:
  - `MOCK:TEMP:A:ENABLE`
  - `MOCK:TEMP:A:LOW`
  - `MOCK:TEMP:A:HIGH`


 ## 🖥️ Graphical User Interface (CS-Studio)

The PVwatcher UI is designed for **CS-Studio Phoebus** using a template-driven architecture. This allows the interface to scale automatically based on your configuration.

### 1. UI Architecture
* **`row_template.bob`**: The master UI component for a single monitoring row. It uses the `$(PV)` macro to map values.
* **`main.bob`**: The top-level display (Auto-generated).
* **`generate_gui.py`**: A utility script that syncs `config.yaml` with the GUI.

### 2. UI Mapping Logic
Each row in the GUI maps the following based on the `config.yaml` entry:

| Widget | PV Suffix | Function |
| :--- | :--- | :--- |
| **LED** | `:STATUS` | **Green (1):** OK | **Red (0):** Alarm/Disconnected |
| **Text Update** | *None* | Displays the live value of the monitored PV. |
| **Text Input** | `:LOW` | Sets the inclusive lower bound. |
| **Text Input** | `:HIGH` | Sets the inclusive upper bound. |
| **Slide Switch** | `:ENABLE` | Toggles monitoring logic for this specific PV. |

### 3. Generating the Display
Whenever you modify the `pvs:` list in `config.yaml`, run the generator script to update the master display:

```bash
# Ensure your Conda environment is active
conda activate pvwatcher-env

# Generate the main.bob file
python generate_gui.py
```

## 🛠️ Troubleshooting (RHEL 8 & Conda)

### PVs are Disconnected (White/Grey in UI)
* **Firewall Configuration:** RHEL 8 blocks EPICS ports by default. Open them using:
  ```bash
  sudo firewall-cmd --add-port=5064/udp --add-port=5065/udp --permanent
  sudo firewall-cmd --reload
```

* **Network Interface:** If running on a machine with multiple interfaces, set the EPICS environment variable before starting the IOC:
  ```bash
export EPICS_CAS_INTF_ADDR_LIST=127.0.0.1  # Replace with your specific IP

```



### GUI Issues

* **Macros Not Resolving:** Ensure `row_template.bob` is in the same directory as `main.bob`.
* **Conda Dependencies:** If `generate_gui.py` fails, ensure `PyYAML` is installed:
  ```bash
conda install pyyaml
```



### Fail-Safe Logic

If `ENABLE` is set to `True` but the target PV is disconnected (returning `None`), the `:STATUS` PV will automatically drop to `0` (Alarm), triggering the Red LED in the GUI.

