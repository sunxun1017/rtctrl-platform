#!/usr/bin/env python3
# Contract-only host stubs. Does not execute the vendor algorithm or claim ERLE.
import argparse
from pathlib import Path
import subprocess
import tempfile
parser=argparse.ArgumentParser()
parser.add_argument('--sdk-include',required=True)
args=parser.parse_args()
source=r'''
#include "aec_bridge.h"
#include <rkaudio_preprocess.h>
#include <cassert>
#include <cstring>
static int active=0, result=512;
extern "C" void* rkaudio_preprocess_init(int rate,int bits,int mic,int ref,RKAUDIOParam* p){
 assert(rate==16000&&bits==16&&mic==1&&ref==1);
 auto* a=static_cast<SKVAECParameter*>(p->aec_param);
 assert(a->pos==1&&a->model_aec_en==EN_DELAY&&a->filter_len==2);
 assert(p->read_size==512&&p->rx_param==nullptr);
 if(p->bf_param){auto* b=static_cast<SKVPreprocessParam*>(p->bf_param);assert(b->model_bf_en==(EN_Fastaec|EN_AES));}
 ++active;return reinterpret_cast<void*>(1);
}
extern "C" void rkaudio_preprocess_destory(void*){--active;}
extern "C" int rkaudio_preprocess_short(void*,short* in,short* out,int n,int*){
 assert(n==512);for(int i=0;i<256;i++){assert(in[2*i+1]==42);out[i]=in[2*i];}return result;
}
int main(){
 assert(!rtctrl_aec_create(2));assert(active==0);
 for(int aes=0;aes<=1;aes++){
 void* a=rtctrl_aec_create(aes);assert(a&&active==1);
 int16_t mic[256],ref[256],out[256];for(int i=0;i<256;i++){mic[i]=i-128;ref[i]=42;out[i]=-5;}
 assert(rtctrl_aec_process256(a,mic,ref,out)==0);assert(!memcmp(mic,out,sizeof(mic)));
 result=510;memset(out,0,sizeof(out));assert(rtctrl_aec_process256(a,mic,ref,out)==-1);for(auto v:out)assert(v==0);result=512;
 assert(rtctrl_aec_process256(a,nullptr,ref,out)==-1);
 assert(rtctrl_aec_reset(a)==0&&active==1);assert(rtctrl_aec_destroy(a)==0&&active==0);
 }
 assert(rtctrl_aec_destroy(nullptr)==0);assert(rtctrl_aec_reset(nullptr)==-1);
}
'''
root=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
    cpp=Path(tmp)/'test.cc';cpp.write_text(source)
    binary=Path(tmp)/'test'
    subprocess.run(['g++','-std=c++11','-I'+str(root),'-I'+args.sdk_include,str(root/'aec_bridge.cc'),str(cpp),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=5)
print('AEC ABI/channel/length/reset/lifetime host contracts passed (stubbed vendor)')
