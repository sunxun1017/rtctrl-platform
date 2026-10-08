#!/usr/bin/env python3
"""Retain paused/pre-publication plug events without premature PS callbacks."""
import difflib
import hashlib
import importlib.util
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('candidate_tools',HERE/'make-candidate-v1.py')
tools=importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)
source=HERE/'candidate-v3/drivers/power/supply/rk817_battery.c'
if hashlib.sha256(source.read_bytes()).hexdigest()!='adbf787f4ad0dca799da551ce6c46f756549fc03f1947fd968f55da7999c3a79':
    raise ValueError('v3 source changed')
text=source.read_text()
text=text.replace('\tint io_error;','\tint io_error;\n\tu64 plug_events;\n\tbool plug_notification_pending;',1)
for name,in_trigger,out_trigger in [('rk809_plug_in_isr',1,0),('rk809_plug_out_isr',0,1)]:
    body=f'''static irqreturn_t {name}(int irq, void *cg)
{{
	struct rk817_battery_device *battery = cg;
	unsigned long flags;
	bool notify;

	spin_lock_irqsave(&battery->state_lock, flags);
	if (battery->stopped || READ_ONCE(battery->io_error)) {{
		spin_unlock_irqrestore(&battery->state_lock, flags);
		return IRQ_HANDLED;
	}}
	/* Cache every owned event, including paused/probe windows. Notify PS
	 * only after successful publication and outside the paused state.
	 */
	battery->plugin_trigger = {in_trigger};
	battery->plugout_trigger = {out_trigger};
	battery->plug_events++;
	battery->plug_notification_pending = true;
	notify = battery->started && !battery->suspended;
	if (notify)
		battery->plug_notification_pending = false;
	spin_unlock_irqrestore(&battery->state_lock, flags);
	if (notify) {{
		power_supply_changed(battery->bat);
		if (battery->is_register_chg_psy)
			power_supply_changed(battery->chg_psy);
	}}
	return IRQ_HANDLED;
}}'''
    text=tools.replace_function(text,name,body)
helper='''static int rk809_bat_refresh_plug_state(struct rk817_battery_device *battery)
{
	unsigned long flags;
	u64 events;
	int plugged, ret;

	spin_lock_irqsave(&battery->state_lock, flags);
	events = battery->plug_events;
	spin_unlock_irqrestore(&battery->state_lock, flags);
	plugged = rk817_bat_field_read(battery, PLUG_IN_STS);
	ret = READ_ONCE(battery->io_error);
	if (ret)
		return ret;
	spin_lock_irqsave(&battery->state_lock, flags);
	/* A threaded IRQ delivered while I2C slept is newer than this read. */
	if (battery->plug_events == events) {
		if (battery->plugin_trigger != !!plugged)
			battery->plug_notification_pending = true;
		battery->plugin_trigger = !!plugged;
		battery->plugout_trigger = !plugged;
	}
	spin_unlock_irqrestore(&battery->state_lock, flags);
	return 0;
}

'''
text=text.replace('static int rk809_charge_init_irqs(',helper+'static int rk809_charge_init_irqs(',1)
text=text.replace('int ret, plug_in_irq, plug_out_irq, plugged;','int ret, plug_in_irq, plug_out_irq;',1)
text=text.replace('\tplugged = rk817_bat_field_read(battery, PLUG_IN_STS);\n\tret = READ_ONCE(battery->io_error);\n\tif (ret) {',
    '\tret = rk809_bat_refresh_plug_state(battery);\n\tif (ret) {',1)
text=text.replace('\tbattery->plugin_trigger = !!plugged;\n\tbattery->plugout_trigger = 0;\n\treturn 0;','\treturn 0;',1)
probe_start=text.index('static int rk817_battery_probe(')
probe_end=text.index('static void rk817_battery_shutdown(',probe_start)
probe=text[probe_start:probe_end]
probe=probe.replace('\tunsigned long flags;','\tunsigned long flags;\n\tbool notify;',1)
probe=probe.replace('\tbattery->started = true;','\tbattery->started = true;\n\tnotify = battery->plug_notification_pending;\n\tbattery->plug_notification_pending = false;',1)
probe=probe.replace('\tspin_unlock_irqrestore(&battery->state_lock, flags);\n\n\treturn 0;',
    '\tspin_unlock_irqrestore(&battery->state_lock, flags);\n\tif (notify) {\n\t\tpower_supply_changed(battery->bat);\n\t\tif (battery->is_register_chg_psy)\n\t\t\tpower_supply_changed(battery->chg_psy);\n\t}\n\n\treturn 0;',1)
text=text[:probe_start]+probe+text[probe_end:]
text=tools.replace_function(text,'rk817_bat_pm_resume','''
static int rk817_bat_pm_resume(struct device *dev)
{
	struct rk817_battery_device *battery = dev_get_drvdata(dev);
	unsigned long flags;
	bool notify = false;
	int ret = 0;

	mutex_lock(&battery->lifecycle_lock);
	if (battery->stopped)
		goto out;
	if (battery->chip_id == RK809_ID) {
		ret = rk809_bat_refresh_plug_state(battery);
		if (ret)
			goto out;
	}
	spin_lock_irqsave(&battery->state_lock, flags);
	battery->suspended = false;
	if (rk817_bat_running(battery)) {
		mod_timer(&battery->caltimer, jiffies + MINUTE(8) * HZ);
		queue_work(battery->bat_monitor_wq, &battery->resume_work);
		notify = battery->plug_notification_pending;
		battery->plug_notification_pending = false;
	}
	spin_unlock_irqrestore(&battery->state_lock, flags);
	if (notify) {
		power_supply_changed(battery->bat);
		if (battery->is_register_chg_psy)
			power_supply_changed(battery->chg_psy);
	}
out:
	mutex_unlock(&battery->lifecycle_lock);
	return ret;
}''')
target=HERE/'candidate-v4/drivers/power/supply/rk817_battery.c'
target.parent.mkdir(parents=True,exist_ok=False)
target.write_text(text,encoding='utf-8',newline='\n')
original=(HERE/'original-v1/drivers/power/supply/rk817_battery.c').read_text()
patch=''.join(difflib.unified_diff(original.splitlines(True),text.splitlines(True),fromfile='a/drivers/power/supply/rk817_battery.c',tofile='b/drivers/power/supply/rk817_battery.c'))
(HERE/'candidate-v4/rk817-lifecycle-review.patch').write_text(patch)
print(hashlib.sha256(target.read_bytes()).hexdigest())
