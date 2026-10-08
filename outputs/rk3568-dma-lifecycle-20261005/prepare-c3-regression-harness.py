#!/usr/bin/env python3
"""Fork earlier immutable suites solely to bind the new C3 provider source."""
from pathlib import Path
p=Path(__file__).resolve().parent
s=(p/'test-pl330-start.py').read_text().replace('test-pl330-start','test-pl330-c3').replace('pl330-start-tests-','pl330-c3-tests-')
s=s.replace('names.insert(names.index("pl330_synchronize_checked"),"pl330_sync_channel")','names.insert(names.index("pl330_synchronize_checked"),"pl330_sync_channel")\n        if "static void pl330_capture_stop_locked(" in text:names.insert(names.index("pl330_sync_channel"),"pl330_capture_stop_locked")')
s=s.replace('names.extend(["dmac_free_threads",', 'if "static void pl330_reader_remove(" in text:names.extend(["pl330_reader_deadline","pl330_reader_remove"])\n    names.extend(["dmac_free_threads",')
(p/'test-pl330-c3.py').write_text(s)
s=(p/'test-pl330-start-shim.h').read_text().replace('struct pl330_dmac {','struct timer_list {int unused;};\nstruct pl330_dmac {')
s=s.replace('    int lifecycle_error;','    int lifecycle_error;atomic_t owned_descs;bool stop_proven;u64 stop_reads;struct timer_list reader_timer;')
s+='''
struct device_attribute {int unused;};
static struct device_attribute dev_attr_rk3568_lifecycle_state;
static inline void device_remove_file(struct device *dev,struct device_attribute *attr){(void)dev;(void)attr;}
#define from_timer(v,t,m) container_of(t,typeof(*(v)),m)
static unsigned long jiffies;
static inline int mod_timer(struct timer_list *timer,unsigned long expires){(void)timer;(void)expires;return 0;}
static inline int del_timer_sync(struct timer_list *timer){(void)timer;return 0;}
'''
(p/'test-pl330-c3-shim.h').write_text(s)
s=(p/'test-pl330-start-main.c').read_text().replace('memset(registers,0,sizeof(registers));dmac.base=registers;','memset(registers,0,sizeof(registers));atomic_store(&dmac.owned_descs.value,2);dmac.base=registers;')
s=s.replace('int main(void){','int main(void){\n    (void)pl330_reader_deadline;')
(p/'test-pl330-c3-main.c').write_text(s)
s=(p/'test-pl330-start-hardware.py').read_text().replace('test-pl330-start-hardware','test-pl330-c3-hardware').replace('test-pl330-start-hw','test-pl330-c3-hw').replace('pl330-start-hw-tests-','pl330-c3-hw-tests-')
(p/'test-pl330-c3-hardware.py').write_text(s)
s=(p/'test-pl330-start-hw-shim.h').read_text().replace('int lifecycle_error;bool pm_failed;', 'int lifecycle_error;bool pm_failed,stop_proven;')
(p/'test-pl330-c3-hw-shim.h').write_text(s)
(p/'test-pl330-c3-hw-main.c').write_bytes((p/'test-pl330-start-hw-main.c').read_bytes())
