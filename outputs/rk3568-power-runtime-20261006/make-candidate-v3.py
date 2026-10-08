#!/usr/bin/env python3
"""Synchronize an IRQ admitted before the suspended publication gate."""
import difflib
import hashlib
from pathlib import Path

HERE=Path(__file__).resolve().parent
source=HERE/'candidate-v2/drivers/power/supply/rk817_battery.c'
if hashlib.sha256(source.read_bytes()).hexdigest()!='5ffced23578a9cfab2c93e4db0ee8570b433ddb83dfc236495d6d7146041c6fd':
    raise ValueError('v2 source changed')
text=source.read_text()
anchor='\tbattery->suspended = true;\n\tspin_unlock_irqrestore(&battery->state_lock, flags);\n'
addition='\t/* An IRQ admitted before the gate may still update cached plug state. */\n\tif (battery->plugin_irq)\n\t\tsynchronize_irq(battery->plugin_irq);\n\tif (battery->plugout_irq)\n\t\tsynchronize_irq(battery->plugout_irq);\n'
if text.count(anchor)!=1:
    raise ValueError('exact pause gate required')
text=text.replace(anchor,anchor+addition)
target=HERE/'candidate-v3/drivers/power/supply/rk817_battery.c'
target.parent.mkdir(parents=True,exist_ok=False)
target.write_text(text,encoding='utf-8',newline='\n')
original=(HERE/'original-v1/drivers/power/supply/rk817_battery.c').read_text()
patch=''.join(difflib.unified_diff(original.splitlines(True),text.splitlines(True),fromfile='a/drivers/power/supply/rk817_battery.c',tofile='b/drivers/power/supply/rk817_battery.c'))
(HERE/'candidate-v3/rk817-lifecycle-review.patch').write_text(patch)
print(hashlib.sha256(target.read_bytes()).hexdigest())
