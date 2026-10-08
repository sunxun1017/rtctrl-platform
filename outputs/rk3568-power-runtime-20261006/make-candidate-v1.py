#!/usr/bin/env python3
"""Create an isolated candidate; never modify the reviewed audio source."""
import difflib
import hashlib
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE / 'original-v1/drivers/power/supply/rk817_battery.c'

def replace_function(source, name, body):
    match = re.search(r'^static[^\n;{}]*\b' + name + r'\s*\([^;{}]*?\)\s*(?=\{)', source, re.M)
    if not match:
        raise ValueError(name)
    opening = source.index('{', match.end())
    end = opening + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[:match.start()] + body.strip() + source[end:]

def main():
    if hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() != '2ce4be10f62292db459570aafcbd2192e767b5bb29bf3396a188e3546f57cb93':
        raise ValueError('Original battery changed')
    text = ORIGINAL.read_text()
    text = text.replace('#include <linux/module.h>', '#include <linux/module.h>\n#include <linux/mutex.h>\n#include <linux/spinlock.h>')
    text = text.replace('struct rk817_battery_device {', '''struct rk817_battery_device {
	struct mutex lifecycle_lock;
	spinlock_t state_lock;
	bool started;
	bool stopped;
	bool suspended;
	int io_error;''')
    helpers = '''
/* Publication is serialized with permanent stop and suspend. */
static bool rk817_bat_running(struct rk817_battery_device *battery)
{
	return READ_ONCE(battery->started) && !READ_ONCE(battery->stopped) &&
	       !READ_ONCE(battery->suspended) && !READ_ONCE(battery->io_error);
}

static void rk817_bat_queue_monitor(struct rk817_battery_device *battery,
				    unsigned long delay)
{
	unsigned long flags;

	spin_lock_irqsave(&battery->state_lock, flags);
	if (rk817_bat_running(battery))
		queue_delayed_work(battery->bat_monitor_wq,
				   &battery->bat_delay_work, delay);
	spin_unlock_irqrestore(&battery->state_lock, flags);
}

/* lifecycle_lock serializes remove, shutdown and PM. Never hold state_lock
 * while joining work/IRQ/timer callbacks. Registered last in devres order.
 */
static void rk817_bat_stop(void *data)
{
	struct rk817_battery_device *battery = data;
	unsigned long flags;

	mutex_lock(&battery->lifecycle_lock);
	spin_lock_irqsave(&battery->state_lock, flags);
	if (battery->stopped) {
		spin_unlock_irqrestore(&battery->state_lock, flags);
		mutex_unlock(&battery->lifecycle_lock);
		return;
	}
	battery->stopped = true;
	battery->started = false;
	spin_unlock_irqrestore(&battery->state_lock, flags);

	if (battery->plugin_irq) {
		devm_free_irq(battery->dev, battery->plugin_irq, battery);
		battery->plugin_irq = 0;
	}
	if (battery->plugout_irq) {
		devm_free_irq(battery->dev, battery->plugout_irq, battery);
		battery->plugout_irq = 0;
	}
	del_timer_sync(&battery->caltimer);
	cancel_work_sync(&battery->resume_work);
	cancel_delayed_work_sync(&battery->bat_delay_work);
	cancel_delayed_work_sync(&battery->calib_delay_work);
	destroy_workqueue(battery->bat_monitor_wq);
	battery->bat_monitor_wq = NULL;
	wake_lock_destroy(&battery->wake_lock);
	mutex_unlock(&battery->lifecycle_lock);
}

/* Caller holds lifecycle_lock, so permanent stop cannot interleave. */
static void rk817_bat_pause(struct rk817_battery_device *battery)
{
	unsigned long flags;

	spin_lock_irqsave(&battery->state_lock, flags);
	battery->suspended = true;
	spin_unlock_irqrestore(&battery->state_lock, flags);
	del_timer_sync(&battery->caltimer);
	cancel_work_sync(&battery->resume_work);
	cancel_delayed_work_sync(&battery->bat_delay_work);
	cancel_delayed_work_sync(&battery->calib_delay_work);
}

static int rk817_bat_validate_pdata(struct rk817_battery_device *battery)
{
	struct battery_platform_data *pdata = battery->pdata;
	u32 i;

	/* interpolate() uses u8 index and size - 1. Preserve valid board tables. */
	if (pdata->ocv_size < 2 || pdata->ocv_size > 255)
		return -EINVAL;
	for (i = 1; i < pdata->ocv_size; i++)
		if (pdata->ocv_table[i] <= pdata->ocv_table[i - 1])
			return -EINVAL;
	/* Existing capacity arithmetic includes capacity * 1000 * 100. */
	if (!pdata->design_capacity || pdata->design_capacity > INT_MAX / 100000 ||
	    pdata->design_qmax < pdata->design_capacity ||
	    pdata->design_qmax > INT_MAX / 100000 ||
	    (pdata->sample_res != SAMPLE_RES_10MR &&
	     pdata->sample_res != SAMPLE_RES_20MR) ||
	    !pdata->monitor_sec || pdata->monitor_sec > UINT_MAX / TIMER_MS_COUNTS)
		return -EINVAL;
	if (battery->chip_id == RK809_ID &&
	    (!pdata->bat_res_down || pdata->bat_res_down > INT_MAX ||
	     pdata->bat_res_up > INT_MAX))
		return -EINVAL;
	return 0;
}
'''
    anchor = 'static void rk817_bat_resume_work(struct work_struct *work);'
    text = text.replace(anchor, helpers + '\n' + anchor, 1)
    text = replace_function(text, 'rk817_bat_field_read', '''
static int rk817_bat_field_read(struct rk817_battery_device *battery,
				enum rk817_battery_fields field_id)
{
	int val, ret;

	if (READ_ONCE(battery->io_error))
		return 0;
	ret = regmap_field_read(battery->rmap_fields[field_id], &val);
	if (ret < 0) {
		cmpxchg(&battery->io_error, 0, ret);
		/* Legacy callers compose unsigned bytes. Do not shift a negative
		 * errno or permit later writes based on a fabricated zero sample.
		 */
		return 0;
	}
	return val;
}''')
    text = replace_function(text, 'rk817_bat_field_write', '''
static int rk817_bat_field_write(struct rk817_battery_device *battery,
				 enum rk817_battery_fields field_id,
				 unsigned int val)
{
	int ret = READ_ONCE(battery->io_error);

	if (ret)
		return ret;
	ret = regmap_field_write(battery->rmap_fields[field_id], val);
	if (ret < 0)
		cmpxchg(&battery->io_error, 0, ret);
	return ret;
}''')
    for name, high, low in [('rk817_bat_get_ioffset','IOFFSET_H','IOFFSET_L'),
                            ('rk817_bat_get_vaclib0','VCALIB0_H','VCALIB0_L'),
                            ('rk817_bat_get_vaclib1','VCALIB1_H','VCALIB1_L')]:
        text = replace_function(text, name, f'''static int {name}(struct rk817_battery_device *battery)
{{
	int high = rk817_bat_field_read(battery, {high});
	int low = rk817_bat_field_read(battery, {low});
	int ret = READ_ONCE(battery->io_error);

	if (ret)
		return ret;
	return (high << 8) | low;
}}''')
    text = replace_function(text, 'rk817_bat_init_voltage_kb', '''
static int rk817_bat_init_voltage_kb(struct rk817_battery_device *battery)
{
	int vcalib0, vcalib1, voltage_k, voltage_b;

	vcalib0 = rk817_bat_get_vaclib0(battery);
	if (vcalib0 < 0)
		return vcalib0;
	vcalib1 = rk817_bat_get_vaclib1(battery);
	if (vcalib1 < 0)
		return vcalib1;
	if (vcalib1 <= vcalib0)
		return -EINVAL;
	if (battery->chip_id == RK809_ID) {
		voltage_k = (1050 - 600) * 1000 / (vcalib1 - vcalib0);
		voltage_b = 1050 - (s64)voltage_k * vcalib1 / 1000;
	} else {
		voltage_k = (4025 - 2300) * 1000 / (vcalib1 - vcalib0);
		voltage_b = 4025 - (s64)voltage_k * vcalib1 / 1000;
	}
	/* All following ADC conversion products use a signed int and u16 ADC. */
	if (!voltage_k || voltage_k > INT_MAX / 65535)
		return -ERANGE;
	battery->voltage_k = voltage_k;
	battery->voltage_b = voltage_b;
	return 0;
}''')
    # Calibration IRQ flag errors cannot run calibration or clear the flag.
    text = text.replace('if (rk817_bat_field_read(battery, CUR_CALIB_UPD)) {',
        'if (rk817_bat_field_read(battery, CUR_CALIB_UPD) > 0 &&\n\t    !READ_ONCE(battery->io_error)) {')
    # Existing worker only calibrates current from IOFFSET; do not change its
    # successful register values. Latch any failed IOFFSET before a write.
    text = text.replace('ioffset = rk817_bat_get_ioffset(battery);',
        'ioffset = rk817_bat_get_ioffset(battery);\n\tif (ioffset < 0)\n\t\treturn;')
    text = replace_function(text, 'rk817_bat_caltimer_isr', '''
static void rk817_bat_caltimer_isr(struct timer_list *t)
{
	struct rk817_battery_device *battery = from_timer(battery, t, caltimer);
	unsigned long flags;

	spin_lock_irqsave(&battery->state_lock, flags);
	if (rk817_bat_running(battery)) {
		mod_timer(&battery->caltimer, jiffies + MINUTE(8) * HZ);
		queue_delayed_work(battery->bat_monitor_wq,
				   &battery->calib_delay_work, msecs_to_jiffies(10));
	}
	spin_unlock_irqrestore(&battery->state_lock, flags);
}''')
    text = replace_function(text, 'rk817_bat_init_caltimer', '''
static void rk817_bat_init_caltimer(struct rk817_battery_device *battery)
{
	timer_setup(&battery->caltimer, rk817_bat_caltimer_isr, 0);
	INIT_DELAYED_WORK(&battery->calib_delay_work, rk817_bat_internal_calib);
}''')
    text = text.replace('static void rk817_bat_init_fg(struct rk817_battery_device *battery)\n{',
        'static int rk817_bat_init_fg(struct rk817_battery_device *battery)\n{\n\tint ret;\n\n\tret = rk817_bat_init_voltage_kb(battery);\n\tif (ret)\n\t\treturn ret;')
    text = text.replace('\trk817_bat_init_voltage_kb(battery);\n\trk817_bat_set_relax_sample', '\trk817_bat_set_relax_sample', 1)
    text = text.replace('\trk817_bat_init_caltimer(battery);\n\trk817_bat_rsoc_init', '\trk817_bat_rsoc_init', 1)
    init_fg_end = 'DBG("OCV_THRE_VOL: 0x%x", rk817_bat_field_read(battery, OCV_THRE_VOL));'
    text = text.replace(init_fg_end, init_fg_end + '\n\treturn READ_ONCE(battery->io_error);', 1)
    text = text.replace('if (pdata->ocv_size <= 0)', 'if (length % sizeof(u32) || pdata->ocv_size < 2 || pdata->ocv_size > 255)', 1)
    text = text.replace('dev_err(dev, "battery res_down missing!\\n");', 'return ret;', 1)
    # Exact end of parser, leave all other successful parameter meanings intact.
    start = text.index('static int rk817_bat_parse_dt(')
    end = text.index('static enum power_supply_property rk817_bat_props', start)
    parser = text[start:end]
    parser = parser.rsplit('\treturn 0;', 1)[0] + '\treturn rk817_bat_validate_pdata(battery);' + parser.rsplit('\treturn 0;', 1)[1]
    text = text[:start] + parser + text[end:]
    # Gate both public battery/chg properties on the sticky I/O error.
    text = text.replace('struct rk817_battery_device *battery = power_supply_get_drvdata(psy);\n\n\tswitch (psp)',
        'struct rk817_battery_device *battery = power_supply_get_drvdata(psy);\n\n\tif (READ_ONCE(battery->io_error))\n\t\treturn READ_ONCE(battery->io_error);\n\n\tswitch (psp)', 1)
    prop_start = text.index('static int rk817_battery_get_property(')
    prop_end = text.index('static const struct power_supply_desc rk817_bat_desc',prop_start)
    prop = text[prop_start:prop_end].replace('\treturn 0;', '\treturn READ_ONCE(battery->io_error);')
    text = text[:prop_start] + prop + text[prop_end:]
    # Monitor body can finish during stop; stop synchronously waits. Requeue is
    # admitted under state_lock so it cannot escape cancellation.
    text = text.replace('\trk817_bat_update_info(battery);\n\trk817_bat_lowpwr_check',
        '\tif (!rk817_bat_running(battery))\n\t\treturn;\n\trk817_bat_update_info(battery);\n\tif (READ_ONCE(battery->io_error))\n\t\treturn;\n\trk817_bat_lowpwr_check', 1)
    text = text.replace('queue_delayed_work(battery->bat_monitor_wq, &battery->bat_delay_work,\n\t\t\t   msecs_to_jiffies(battery->monitor_ms));',
        'rk817_bat_queue_monitor(battery, msecs_to_jiffies(battery->monitor_ms));', 1)
    for name in ['rk809_plug_in_isr','rk809_plug_out_isr']:
        begin = text.index('static irqreturn_t ' + name)
        after = text.index('battery = (struct rk817_battery_device *)cg;', begin)
        insertion = after + len('battery = (struct rk817_battery_device *)cg;')
        text = text[:insertion] + '\n\tif (!rk817_bat_running(battery))\n\t\treturn IRQ_HANDLED;' + text[insertion:]
    text = replace_function(text, 'rk809_charge_init_irqs', '''
static int rk809_charge_init_irqs(struct rk817_battery_device *battery)
{
	struct rk808 *rk817 = battery->rk817;
	int ret, plug_in_irq, plug_out_irq, plugged;

	plug_in_irq = regmap_irq_get_virq(rk817->irq_data, RK817_IRQ_PLUG_IN);
	if (plug_in_irq <= 0)
		return plug_in_irq ? plug_in_irq : -EINVAL;
	plug_out_irq = regmap_irq_get_virq(rk817->irq_data, RK817_IRQ_PLUG_OUT);
	if (plug_out_irq <= 0)
		return plug_out_irq ? plug_out_irq : -EINVAL;
	ret = devm_request_threaded_irq(battery->dev, plug_in_irq, NULL,
					rk809_plug_in_isr,
					IRQF_TRIGGER_RISING | IRQF_ONESHOT,
					"rk817_plug_in", battery);
	if (ret)
		return ret;
	battery->plugin_irq = plug_in_irq;
	ret = devm_request_threaded_irq(battery->dev, plug_out_irq, NULL,
					rk809_plug_out_isr,
					IRQF_TRIGGER_RISING | IRQF_ONESHOT,
					"rk817_plug_out", battery);
	if (ret)
		goto err_plugin;
	battery->plugout_irq = plug_out_irq;
	plugged = rk817_bat_field_read(battery, PLUG_IN_STS);
	ret = READ_ONCE(battery->io_error);
	if (ret) {
		devm_free_irq(battery->dev, battery->plugout_irq, battery);
		battery->plugout_irq = 0;
		goto err_plugin;
	}
	battery->plugin_trigger = !!plugged;
	battery->plugout_trigger = 0;
	return 0;

err_plugin:
	devm_free_irq(battery->dev, battery->plugin_irq, battery);
	battery->plugin_irq = 0;
	return ret;
}''')
    probe_start = text.index('static int rk817_battery_probe(')
    probe_end = text.index('static void rk817_battery_shutdown(', probe_start)
    probe = text[probe_start:probe_end]
    probe = probe.replace('devm_kzalloc(&client->dev, sizeof(*battery), GFP_KERNEL)', 'devm_kzalloc(&pdev->dev, sizeof(*battery), GFP_KERNEL)')
    probe = probe.replace('if (!battery)\n\t\treturn -EINVAL;', 'if (!battery)\n\t\treturn -ENOMEM;')
    probe = probe.replace('battery->dev = &pdev->dev;', 'battery->dev = &pdev->dev;\n\tbattery->pdev = pdev;\n\tmutex_init(&battery->lifecycle_lock);\n\tspin_lock_init(&battery->state_lock);')
    probe = probe.replace('\tint i,  ret;', '\tint i, ret;\n\tunsigned long flags;')
    old = probe[probe.index('\trk817_bat_init_info(battery);'):probe.index('\tret = rk817_bat_init_power_supply(battery);')]
    new = '''	rk817_bat_init_info(battery);
	battery->bat_monitor_wq = alloc_ordered_workqueue("%s",
			WQ_MEM_RECLAIM | WQ_FREEZABLE, "rk817-bat-monitor-wq");
	if (!battery->bat_monitor_wq)
		return -ENOMEM;
	INIT_DELAYED_WORK(&battery->bat_delay_work, rk817_battery_work);
	INIT_WORK(&battery->resume_work, rk817_bat_resume_work);
	rk817_bat_init_caltimer(battery);
	wake_lock_init(&battery->wake_lock, WAKE_LOCK_SUSPEND, "rk817_bat_lock");
	ret = rk817_bat_init_fg(battery);
	if (ret)
		goto err_stop;
	rk817_battery_debug_info(battery);
	rk817_bat_update_info(battery);
	ret = READ_ONCE(battery->io_error);
	if (ret)
		goto err_stop;
	rk817_bat_output_info(battery);

'''
    probe = probe.replace(old, new)
    after = probe.index('\tret = rk817_bat_init_power_supply(battery);')
    head, tail = probe[:after], probe[after:]
    tail = tail.replace('\t\treturn ret;', '\t\tgoto err_stop;')
    tail = tail.replace('if (battery->chip_id == RK809_ID)\n\t\trk809_charge_init_irqs(battery);',
        'if (battery->chip_id == RK809_ID) {\n\t\tret = rk809_charge_init_irqs(battery);\n\t\tif (ret)\n\t\t\tgoto err_stop;\n\t}')
    tail = tail.replace('\twake_lock_init(&battery->wake_lock, WAKE_LOCK_SUSPEND,\n\t\t       "rk817_bat_lock");', '''	ret = devm_add_action_or_reset(battery->dev, rk817_bat_stop, battery);
	if (ret)
		return ret;
	spin_lock_irqsave(&battery->state_lock, flags);
	battery->started = true;
	mod_timer(&battery->caltimer, jiffies + MINUTE(8) * HZ);
	queue_delayed_work(battery->bat_monitor_wq, &battery->bat_delay_work,
			   msecs_to_jiffies(TIMER_MS_COUNTS * 5));
	spin_unlock_irqrestore(&battery->state_lock, flags);''')
    tail = tail.replace('\treturn 0;\n}', '\treturn 0;\n\nerr_stop:\n\trk817_bat_stop(battery);\n\treturn ret;\n}', 1)
    text = text[:probe_start] + head + tail + text[probe_end:]
    text = replace_function(text, 'rk817_battery_shutdown', '''
static void rk817_battery_shutdown(struct platform_device *pdev)
{
	rk817_bat_stop(platform_get_drvdata(pdev));
}

static int rk817_battery_remove(struct platform_device *pdev)
{
	rk817_bat_stop(platform_get_drvdata(pdev));
	return 0;
}''')
    text = text.replace('.probe = rk817_battery_probe,', '.probe = rk817_battery_probe,\n\t.remove = rk817_battery_remove,')
    text = replace_function(text, 'rk817_get_rtc_sec', '''
static time64_t rk817_get_rtc_sec(void)
{
	struct rtc_time tm;
	struct rtc_device *rtc = rtc_class_open(CONFIG_RTC_HCTOSYS_DEVICE);
	time64_t seconds = 0;

	if (!rtc)
		return 0;
	if (!rtc_read_time(rtc, &tm) && !rtc_valid_tm(&tm))
		seconds = rtc_tm_to_time64(&tm);
	rtc_class_close(rtc);
	return seconds;
}''')
    text = replace_function(text, 'rk817_bat_rtc_sleep_sec', '''
static int rk817_bat_rtc_sleep_sec(struct rk817_battery_device *battery)
{
	time64_t now = rk817_get_rtc_sec();
	time64_t interval;

	if (!now || !battery->rtc_base || now <= battery->rtc_base)
		return 0;
	interval = now - battery->rtc_base;
	return min(interval, (time64_t)INT_MAX);
}''')
    text = text.replace('\tcancel_delayed_work_sync(&battery->bat_delay_work);\n\n\tbattery->s2r = false;', '''	mutex_lock(&battery->lifecycle_lock);
	if (battery->stopped) {
		mutex_unlock(&battery->lifecycle_lock);
		return 0;
	}
	rk817_bat_pause(battery);
	battery->s2r = false;''', 1)
    start = text.index('static int  rk817_bat_pm_suspend(')
    end = text.index('static int rk817_bat_rtc_sleep_sec(', start)
    suspend = text[start:end].replace('\treturn 0;\n}', '\tmutex_unlock(&battery->lifecycle_lock);\n\treturn 0;\n}', 1)
    text = text[:start] + suspend + text[end:]
    text = text.replace('\tint interval_sec = 0, time_step = 0, pwroff_vol;\n\n\tbattery->s2r', '\tint interval_sec = 0, time_step = 0, pwroff_vol;\n\n\tif (!rk817_bat_running(battery))\n\t\treturn;\n\tbattery->s2r', 1)
    text = text.replace('queue_delayed_work(battery->bat_monitor_wq, &battery->bat_delay_work,\n\t\t\t   msecs_to_jiffies(1000));', 'rk817_bat_queue_monitor(battery, msecs_to_jiffies(1000));', 1)
    text = replace_function(text, 'rk817_bat_pm_resume', '''
static int rk817_bat_pm_resume(struct device *dev)
{
	struct rk817_battery_device *battery = dev_get_drvdata(dev);
	unsigned long flags;

	mutex_lock(&battery->lifecycle_lock);
	spin_lock_irqsave(&battery->state_lock, flags);
	if (!battery->stopped) {
		battery->suspended = false;
		if (rk817_bat_running(battery)) {
			mod_timer(&battery->caltimer, jiffies + MINUTE(8) * HZ);
			queue_work(battery->bat_monitor_wq, &battery->resume_work);
		}
	}
	spin_unlock_irqrestore(&battery->state_lock, flags);
	mutex_unlock(&battery->lifecycle_lock);
	return 0;
}''')
    output = HERE / 'candidate-v1/drivers/power/supply/rk817_battery.c'
    output.parent.mkdir(parents=True, exist_ok=False)
    output.write_text(text, encoding='utf-8', newline='\n')
    patch = ''.join(difflib.unified_diff(ORIGINAL.read_text().splitlines(True), text.splitlines(True),
        fromfile='a/drivers/power/supply/rk817_battery.c', tofile='b/drivers/power/supply/rk817_battery.c'))
    (HERE / 'candidate-v1/rk817-lifecycle-review.patch').write_text(patch, encoding='utf-8', newline='\n')
    print(hashlib.sha256(output.read_bytes()).hexdigest())

if __name__ == '__main__':
    main()
