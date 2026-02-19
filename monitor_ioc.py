#!/usr/bin/env python3
"""
Monitor IOC.

This IOC loads a list of target PVs from a configuration file, creates local PVs
to set bounds and enable monitoring for each target, and publishes a summary status.

It uses caproto.server for the IOC and caproto.asyncio.client for monitoring
external PVs.
"""

import asyncio
import logging
import yaml
import sys
from caproto import ChannelType
from caproto.server import PVGroup, ioc_arg_parser, run, pvproperty
from caproto.asyncio.client import Context


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('MonitorIOC')


def load_config(config_path='config.yaml'):
    """Load the configuration file."""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config.get('target_pvs', [])
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)


def create_monitor_ioc_class(target_pvs):
    """
    Dynamically create the MonitorIOC class with PVs for each target.

    We construct the class dictionary first, then use `type()` to create the class.
    This ensures that PVGroupMeta processes all pvproperty instances correctly.
    """

    # Base attributes for the class
    class_dict = {
        '__module__': __name__,
        'target_pvs_list': target_pvs,
    }

    # -------------------------------------------------------------------------
    # Define Methods
    # -------------------------------------------------------------------------

    def __init__(self, *args, **kwargs):
        super(type(self), self).__init__(*args, **kwargs)
        self.target_values = {t: None for t in target_pvs}
        self.client_context = None
        self._monitored_pvs = []
        self._monitor_tasks = []

    class_dict['__init__'] = __init__

    # -------------------------------------------------------------------------
    # Define Static PVs (Master Enable, Summary Status)
    # -------------------------------------------------------------------------

    async def master_enable_putter(self, instance, value):
        logger.info(f"Master Enable Changed to {value}")
        await self._update_summary(master_enable_override=value)
        return value

    async def master_enable_startup(self, instance, async_lib):
        logger.info("Starting monitoring client (asyncio)...")
        # Create client context
        self.client_context = Context()

        # Connect to targets
        logger.info(f"Connecting to targets: {self.target_pvs_list}")
        try:
            pvs = await self.client_context.get_pvs(*self.target_pvs_list)
            self._monitored_pvs = pvs  # Keep reference
        except Exception as e:
            logger.error(f"Failed to get PVs: {e}")
            return

        # Start monitoring loops
        for pv in pvs:
            logger.info(f"Subscribing to {pv.name}")

            # Read initial value to confirm connection
            try:
                initial_read = await pv.read()

                # Update initial state
                val = initial_read.data
                try:
                    if hasattr(val, '__iter__') and not isinstance(val, str):
                        v = val[0]
                    else:
                        v = val
                except Exception:
                    v = val
                self.target_values[pv.name] = v

            except Exception as e:
                logger.error(f"Failed to read initial value of {pv.name}: {e}")

            # Create task for monitoring
            # Use ensure_future for Python 3.6 compatibility
            task = asyncio.ensure_future(self._monitor_loop(pv))
            self._monitor_tasks.append(task)

            # Trigger initial summary update
            await self._update_summary()

    master_enable_prop = pvproperty(value=1, name='MONITOR:MASTER_ENABLE', dtype=ChannelType.INT)
    master_enable_prop = master_enable_prop.putter(master_enable_putter)
    master_enable_prop = master_enable_prop.startup(master_enable_startup)

    class_dict['master_enable'] = master_enable_prop

    summary_status_prop = pvproperty(value=1, name='MONITOR:SUMMARY_STATUS', dtype=ChannelType.INT, read_only=True)
    class_dict['summary_status'] = summary_status_prop

    # -------------------------------------------------------------------------
    # Define Helper Methods
    # -------------------------------------------------------------------------

    async def _monitor_loop(self, pv):
        """Async loop to monitor a single PV."""
        logger.info(f"Starting monitor loop for {pv.name}")
        sub = pv.subscribe(data_type='time')

        try:
            async for response in sub:
                val = response.data
                try:
                    if hasattr(val, '__iter__') and not isinstance(val, str):
                        v = val[0]
                    else:
                        v = val
                except Exception:
                    v = val

                self.target_values[pv.name] = v
                # logger.info(f"Update received for {pv.name}: {v}")
                await self._update_summary()
        except Exception as e:
            logger.error(f"Monitor loop failed for {pv.name}: {e}")

    class_dict['_monitor_loop'] = _monitor_loop

    async def _update_summary(self, master_enable_override=None):
        if master_enable_override is None:
            master_enable = self.master_enable.value
        else:
            master_enable = master_enable_override

        if master_enable == 0:
            if self.summary_status.value != 1:
                logger.info("Master disabled. Setting SUMMARY_STATUS to 1.")
                await self.summary_status.write(1)
            return

        all_ok = True

        for target in self.target_pvs_list:
            attr_suffix = target.replace(':', '_')

            if not hasattr(self, f"{attr_suffix}_enable"):
                continue

            enable_pv = getattr(self, f"{attr_suffix}_enable")
            low_pv = getattr(self, f"{attr_suffix}_low")
            high_pv = getattr(self, f"{attr_suffix}_high")

            is_enabled = enable_pv.value
            low_limit = low_pv.value
            high_limit = high_pv.value

            current_value = self.target_values.get(target)

            if is_enabled and current_value is not None:
                if current_value < low_limit or current_value > high_limit:
                    all_ok = False
                    logger.info(f"Alarm on {target}: Val={current_value} (Limits: {low_limit}-{high_limit})")
                    break

        new_status = 1 if all_ok else 0
        if self.summary_status.value != new_status:
            logger.info(f"Updating SUMMARY_STATUS to {new_status}")
            await self.summary_status.write(new_status)

    class_dict['_update_summary'] = _update_summary

    # -------------------------------------------------------------------------
    # Define Dynamic PVs and Putters
    # -------------------------------------------------------------------------

    async def generic_putter(group, instance, value):
        logger.info(f"Generic putter called for {instance.name} with value {value}")
        # Schedule update check
        async def check_after():
            await asyncio.sleep(0.01)
            await group._update_summary()

        # Use ensure_future for 3.6 compatibility
        asyncio.ensure_future(check_after())
        return value

    for target in target_pvs:
        attr_suffix = target.replace(':', '_')

        # ENABLE
        p_enable = pvproperty(value=1, name=f'{target}:ENABLE', dtype=ChannelType.INT)
        p_enable = p_enable.putter(generic_putter)
        class_dict[f"{attr_suffix}_enable"] = p_enable

        # LOW
        p_low = pvproperty(value=0.0, name=f'{target}:LOW', dtype=ChannelType.DOUBLE)
        p_low = p_low.putter(generic_putter)
        class_dict[f"{attr_suffix}_low"] = p_low

        # HIGH
        p_high = pvproperty(value=100.0, name=f'{target}:HIGH', dtype=ChannelType.DOUBLE)
        p_high = p_high.putter(generic_putter)
        class_dict[f"{attr_suffix}_high"] = p_high

    DynamicMonitorIOC = type('DynamicMonitorIOC', (PVGroup,), class_dict)

    return DynamicMonitorIOC


if __name__ == '__main__':
    target_pvs = load_config()
    IOCClass = create_monitor_ioc_class(target_pvs)

    ioc_options, run_options = ioc_arg_parser(
        default_prefix='',
        desc='Monitor IOC'
    )

    ioc = IOCClass(**ioc_options)
    run(ioc.pvdb, **run_options)
