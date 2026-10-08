#!/usr/bin/env python3
"""Address independent review of IRQ ownership and property error gates."""
import difflib
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent

def main():
    source = HERE / 'candidate-v1/drivers/power/supply/rk817_battery.c'
    text = source.read_text()
    if hashlib.sha256(source.read_bytes()).hexdigest() != 'f39f129abd3b8a02321c2e031d6a4242e01423779baee0bc07ec427929a72664':
        raise ValueError('v1 changed')
    text = text.replace('devm_free_irq(battery->dev, battery->plugin_irq, battery)', 'free_irq(battery->plugin_irq, battery)')
    text = text.replace('devm_free_irq(battery->dev, battery->plugout_irq, battery)', 'free_irq(battery->plugout_irq, battery)')
    text = text.replace('devm_request_threaded_irq(battery->dev, plug_in_irq, NULL,', 'request_threaded_irq(plug_in_irq, NULL,')
    text = text.replace('devm_request_threaded_irq(battery->dev, plug_out_irq, NULL,', 'request_threaded_irq(plug_out_irq, NULL,')
    text = text.replace(' * while joining work/IRQ/timer callbacks. Registered last in devres order.',
        ' * while joining work/IRQ/timer callbacks. Registered last in devres order.\n * IRQs are non-devm and owned only here, including the release_all fallback.\n * release_all detaches devres nodes before actions, so devm_free_irq here\n * would conflict with detached IRQ release nodes.')
    text = text.replace('\tint val, ret;\n\n\tif (READ_ONCE(battery->io_error))', '\tunsigned int val;\n\tint ret;\n\n\tif (READ_ONCE(battery->io_error))', 1)
    text = text.replace('u32 out_value;\n\tint length, ret;', 'u32 out_value;\n\tint length, ret;', 1)
    text = text.replace('of_property_read_u32(np, "register_chg_psy",\n\t\t\t\t\t   &battery->is_register_chg_psy);',
        'of_property_read_u32(np, "register_chg_psy", &out_value);\n\t\tif (!ret)\n\t\t\tbattery->is_register_chg_psy = !!out_value;')
    # Keep the exact successful board conversion, use wide intermediates so
    # the original 100/100 divider cannot overflow before the division.
    text = text.replace('vol * battery->pdata->bat_res_up /', '(s64)vol * battery->pdata->bat_res_up /')
    text = text.replace('int vcalib0, vcalib1, voltage_k, voltage_b;', 'int vcalib0, vcalib1, voltage_k, voltage_b;\n\ts64 maximum_voltage;')
    text = text.replace('\tbattery->voltage_k = voltage_k;', '''	maximum_voltage = (s64)voltage_k * 65535 / 1000 + voltage_b;
	if (battery->chip_id == RK809_ID) {
		if (!battery->pdata || !battery->pdata->bat_res_down)
			return -EINVAL;
		maximum_voltage += maximum_voltage * battery->pdata->bat_res_up /
				   battery->pdata->bat_res_down;
		if (maximum_voltage > INT_MAX)
			return -ERANGE;
	}
	battery->voltage_k = voltage_k;''', 1)
    text = text.replace('\t\trk817_bat_init_voltage_kb(battery);\n\t\trk817_bat_field_write(battery, CUR_CALIB_UPD, 0x01);', '''		int ret = rk817_bat_init_voltage_kb(battery);

		if (ret) {
			cmpxchg(&battery->io_error, 0, ret);
			return;
		}
		rk817_bat_field_write(battery, CUR_CALIB_UPD, 0x01);''', 1)
    text = text.replace('\tint ret = 0;\n\n\tif (battery->plugin_trigger)',
        '\tint ret = 0;\n\n\tif (READ_ONCE(battery->io_error))\n\t\treturn READ_ONCE(battery->io_error);\n\n\tif (battery->plugin_trigger)', 1)
    text = text.replace('\tfor (i = 1; i < pdata->ocv_size; i++)', '\tfor (i = 0; i < pdata->ocv_size; i++)\n\t\tif (!pdata->ocv_table[i] || pdata->ocv_table[i] > INT_MAX)\n\t\t\treturn -EINVAL;\n\tfor (i = 1; i < pdata->ocv_size; i++)', 1)
    text = text.replace('static void rk817_battery_work(struct work_struct *work)\n{', 'static void rk817_battery_work(struct work_struct *work)\n{\n\tint ret;', 1)
    text = text.replace('int ret = rk817_bat_init_voltage_kb(battery);', 'ret = rk817_bat_init_voltage_kb(battery);', 1)
    text = text.replace('\trk817_bat_pause(battery);\n', '\trk817_bat_pause(battery);\n\tif (READ_ONCE(battery->io_error)) {\n\t\tmutex_unlock(&battery->lifecycle_lock);\n\t\treturn READ_ONCE(battery->io_error);\n\t}\n', 1)
    start = text.index('static int  rk817_bat_pm_suspend(')
    end = text.index('static int rk817_bat_rtc_sleep_sec(', start)
    section = text[start:end].replace('\tmutex_unlock(&battery->lifecycle_lock);\n\treturn 0;\n}', '\tmutex_unlock(&battery->lifecycle_lock);\n\treturn READ_ONCE(battery->io_error);\n}', 1)
    text = text[:start] + section + text[end:]
    text = text.replace('\tbattery->rsoc = rk817_bat_get_rsoc(battery);\n\tinterval_sec', '\tbattery->rsoc = rk817_bat_get_rsoc(battery);\n\tif (READ_ONCE(battery->io_error))\n\t\treturn;\n\tinterval_sec', 1)
    text = text.replace('\trk817_bat_save_data(battery);\n\n\t/* charge/lowpower lock:', '\trk817_bat_save_data(battery);\n\tif (READ_ONCE(battery->io_error))\n\t\treturn;\n\n\t/* charge/lowpower lock:', 1)
    diagnostics = '\tDBG("name: 0x%x", rk817_bat_field_read(battery, CHIP_NAME_H));\n\tDBG("%x\\n", rk817_bat_field_read(battery, CHIP_NAME_L));\n\tDBG("driver version %s\\n", DRIVER_VERSION);\n'
    text = text.replace(diagnostics+'\n', '', 1)
    text = text.replace('\tret = devm_add_action_or_reset(battery->dev, rk817_bat_stop, battery);', diagnostics+'\tret = READ_ONCE(battery->io_error);\n\tif (ret)\n\t\tgoto err_stop;\n\tret = devm_add_action_or_reset(battery->dev, rk817_bat_stop, battery);', 1)
    target = HERE / 'candidate-v2/drivers/power/supply/rk817_battery.c'
    target.parent.mkdir(parents=True, exist_ok=False)
    target.write_text(text, encoding='utf-8', newline='\n')
    original = (HERE / 'original-v1/drivers/power/supply/rk817_battery.c').read_text()
    patch = ''.join(difflib.unified_diff(original.splitlines(True),text.splitlines(True),
        fromfile='a/drivers/power/supply/rk817_battery.c', tofile='b/drivers/power/supply/rk817_battery.c'))
    (HERE / 'candidate-v2/rk817-lifecycle-review.patch').write_text(patch, encoding='utf-8', newline='\n')
    print(hashlib.sha256(target.read_bytes()).hexdigest())

if __name__ == '__main__':
    main()
