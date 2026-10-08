#!/usr/bin/env python3
"""Preserve failed clean-baseline build and prepare the existing header fix."""
from pathlib import Path

HERE=Path(__file__).resolve().parent
source=(HERE/'build-kbuild-v2.py').read_text()
source=source.replace("output=HERE/'build/kbuild-v2'", "output=HERE/'build/kbuild-v3'")
anchor="    old=HERE/'original-v1/drivers/power/supply/rk817_battery.c'"
insert="""    # The baseline audio config needs its already-reviewed arm64 include fix.
    # All twelve public patches match the current dedicated audio kernel.
    public=ROOT/'platforms/rk3568/boards/aiot-3568pq/patches'
    applied={}
    for number in range(1,13):
        matches=list(public.glob(f'{number:04d}-*.patch'))
        if len(matches)!=1:
            raise ValueError('Unique baseline public patch required')
        patch=matches[0]
        applied[patch.relative_to(ROOT).as_posix()]=sha(patch)
        run(f'baseline-{number:02d}-check',['git','-C',str(source),'apply','--check',str(patch)])
        run(f'baseline-{number:02d}-apply',['git','-C',str(source),'apply',str(patch)])
"""
source=source.replace(anchor,insert+anchor,1)
source=source.replace("    (build/'.config').write_text(config)", "    config=config.replace('CONFIG_CHARGER_BQ24735=y','# CONFIG_CHARGER_BQ24735 is not set')\n    (build/'.config').write_text(config)")
source=source.replace("'config_delta':['CONFIG_BATTERY_RK817=n -> y']", "'config_delta':['CONFIG_BATTERY_RK817=n -> y','CONFIG_CHARGER_BQ24735=y -> n'],'baseline_patches_sha256':applied")
source=source.replace("    run('object',common+['V=1','-j4','drivers/power/supply/rk817_battery.o'])", "    for symbol in ['CHARGER_RK817','CHARGER_BQ24735','CHARGER_BQ25700','CHARGER_BQ25713']:\n        if '# CONFIG_'+symbol+' is not set' not in config:\n            raise ValueError('External/internal charger must remain disabled')\n    run('object',common+['V=1','-j4','drivers/power/supply/rk817_battery.o'])")
(HERE/'build-kbuild-v3.py').write_text(source,encoding='utf-8',newline='\n')
print('prepared private build-v3')
