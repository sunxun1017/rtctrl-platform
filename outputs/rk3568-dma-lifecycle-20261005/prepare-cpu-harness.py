#!/usr/bin/env python3
"""Create separate CPU-bound harness; frozen earlier evidence stays untouched."""
from pathlib import Path
p=Path(__file__).resolve().parent
s=(p/'test-asoc-trigger.py').read_text()
s=s.replace('p.add_argument("--label",required=True);a=p.parse_args()', 'p.add_argument("--label",required=True);p.add_argument("--cpu-source",type=Path,required=True);a=p.parse_args()')
s=s.replace('trigger-tests-','trigger-cpu-tests-')
s=s.replace('test-asoc-trigger.py','test-asoc-cpu.py').replace('test-asoc-trigger-main.c','test-asoc-cpu-main.c')
s=s.replace('names=["test-asoc-cpu.py"','names=["test-asoc-cpu-shim.h","test-asoc-cpu.py"')
anchor='    for path,data in sources.items():'
insertion='''    cpu=a.cpu_source.read_bytes();cpu_names=["i2s_checked_first_error","i2s_checked_error_locked","i2s_checked_stop_locked","i2s_checked_component_trigger"];cpu_excerpts={name:function(cpu.decode(),name) for name in cpu_names}
    cpu_header=(ROOT/"third_party/linux-rk3588/sound/soc/rockchip/rockchip_i2s_tdm.h").read_bytes();(out/"cpu-register-input.h").write_bytes(cpu_header);(out/"cpu-source-input.c").write_bytes(cpu)
    cpu_extract="\\n\\n".join(cpu_excerpts.values());(out/"cpu-extracted.c").write_text(cpu_extract)
'''
s=s.replace(anchor,insertion+anchor)
s=s.replace("+extracted+'\\n#include", "+'#include \"test-asoc-cpu-shim.h\"\\n'+cpu_extract+'\\n'+extracted+'\\n#include")
s=s.replace('result["passed"]=not failed;', 'result["cpu_source_sha256"]=sha(cpu);result["cpu_header_sha256"]=sha(cpu_header);result["cpu_excerpts_sha256"]={n:sha(b.encode()) for n,b in cpu_excerpts.items()};result["cpu_final_rebind_pending"]=True;result["passed"]=not failed;')
(p/'test-asoc-cpu.py').write_text(s)
s=(p/'test-asoc-trigger-main.c').read_text()
s=s.replace('if(id==0 && conflict_new_direction)return -EBUSY;', 'if(id==0 && conflict_new_direction)return i2s_checked_component_trigger(c,s,cmd);')
s=s.replace('memset(start_errors,0,sizeof(start_errors));', 'memset(&cpu_fixture,0,sizeof(cpu_fixture));spin_lock_init(&cpu_fixture.lock);cpu_fixture.checked_lifecycle=true;cpu_fixture.ready=true;cpu_fixture.stop_proven=true;cpu_io_attempts=0;\n memset(start_errors,0,sizeof(start_errors));')
s=s.replace('other_direction_active=true;conflict_new_direction=true;', 'other_direction_active=true;conflict_new_direction=true;cpu_fixture.started=BIT(SNDRV_PCM_STREAM_CAPTURE);')
s=s.replace('CHECK(other_direction_active && issue_calls', 'CHECK(cpu_fixture.started==BIT(SNDRV_PCM_STREAM_CAPTURE) && cpu_io_attempts==0);CHECK(i2s_checked_stop_locked(&cpu_fixture,SNDRV_PCM_STREAM_PLAYBACK,false)==0 && cpu_fixture.started==BIT(SNDRV_PCM_STREAM_CAPTURE) && cpu_io_attempts==0);CHECK(other_direction_active && issue_calls')
s=s.replace('trace[trace_count++]=10+id;stop_count[id]++;active_member[id]=false;\n if(id==1)', 'trace[trace_count++]=10+id;stop_count[id]++;active_member[id]=false;\n if(id==0 && conflict_new_direction)return i2s_checked_component_trigger(c,s,cmd);\n if(id==1)')
(p/'test-asoc-cpu-main.c').write_text(s)
