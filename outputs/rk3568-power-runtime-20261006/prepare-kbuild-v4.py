#!/usr/bin/env python3
"""Compile the final v3 source without changing the successful v2 output."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
text=(HERE/'build-kbuild-v3.py').read_text()
text=text.replace("output=HERE/'build/kbuild-v3'","output=HERE/'build/kbuild-v4'")
text=text.replace("candidate=HERE/'candidate-v2/drivers/power/supply/rk817_battery.c'","candidate=HERE/'candidate-v3/drivers/power/supply/rk817_battery.c'")
text=text.replace("patch_path=HERE/'candidate-v2/rk817-lifecycle-review.patch'","patch_path=HERE/'candidate-v3/rk817-lifecycle-review.patch'")
text=text.replace("'rk817_bat_pm_suspend','rk817_bat_pm_resume']", "'rk817_bat_pm_suspend','rk817_bat_pm_resume','synchronize_irq']")
(HERE/'build-kbuild-v4.py').write_text(text,encoding='utf-8',newline='\n')
print('prepared final separate in-tree Kbuild')
