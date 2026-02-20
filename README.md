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
