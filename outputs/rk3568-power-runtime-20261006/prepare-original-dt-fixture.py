#!/usr/bin/env python3
"""Expose original board cells to the property dependency wrapper exactly."""
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
data=json.loads((HERE/'build/dtb-v2/original-properties.json').read_text())['decoded']
text='/* Original board DT cells; not a new battery calibration. */\n'
text+='static const u32 original_ocv[] = {'+','.join(str(v) for v in data['ocv_table'])+'};\n'
text+='static int original_dt_u32(const char *name,u32 *value) {\n'
for name,values in data.items():
    if name not in ['compatible','ocv_table']:
        text+=f'    if (!strcmp(name,"{name}")) {{ *value={values[0]}; return 0; }}\n'
text+='    return -EINVAL;\n}\n'
(HERE/'original-dt-fixture.h').write_text(text)
print('original 21 OCV cells and 14 scalar cells')
