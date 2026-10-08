#!/usr/bin/env python3
"""Build the final event-cache candidate in a fresh in-tree output."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
text=(HERE/'build-kbuild-v4.py').read_text()
text=text.replace("output=HERE/'build/kbuild-v4'","output=HERE/'build/kbuild-v5'")
text=text.replace("candidate=HERE/'candidate-v3/drivers/power/supply/rk817_battery.c'","candidate=HERE/'candidate-v4/drivers/power/supply/rk817_battery.c'")
text=text.replace("patch_path=HERE/'candidate-v3/rk817-lifecycle-review.patch'","patch_path=HERE/'candidate-v4/rk817-lifecycle-review.patch'")
text=text.replace("'synchronize_irq']", "'synchronize_irq','rk809_bat_refresh_plug_state']")
(HERE/'build-kbuild-v5.py').write_text(text,encoding='utf-8',newline='\n')
print('prepared final event-cache in-tree Kbuild')
