from pathlib import Path
import subprocess
f=Path('/userdata/rtctrl-face-video');o=f/'cache-swap';pid=(f/'video.pid').read_text().strip()
with (o/'cache-record.txt').open('w') as log:subprocess.run(['perf','record','-e','armv8_cortex_a53/l2d_cache_refill/','-c','65536','-g','-p',pid,'-o',str(o/'cache.data'),'--','sleep','20'],stdout=log,stderr=log,check=True)
with (o/'cache-self.txt').open('w') as log:subprocess.run(['perf','report','--stdio','--no-children','-g','none','--percent-limit','0.5','-i',str(o/'cache.data')],stdout=log,stderr=log,check=True)
print('DONE')
