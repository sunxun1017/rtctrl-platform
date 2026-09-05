#define main vendor_server_main
#include SERVER_SOURCE
#undef main
#include <sys/wait.h>
static int scenario;
extern "C" rk_aiq_sys_ctx_t* rk_aiq_uapi2_sysctl_init(const char*,const char*,rk_aiq_error_cb,rk_aiq_metas_cb) { return NULL; }
extern "C" void rk_aiq_uapi2_sysctl_setListenStrmStatus(rk_aiq_sys_ctx_t*,bool) { _exit(90); }
extern "C" void rk_aiq_uapi2_sysctl_setMulCamConc(const rk_aiq_sys_ctx_t*,bool) { _exit(91); }
extern "C" XCamReturn rk_aiq_uapi2_sysctl_prepare(const rk_aiq_sys_ctx_t*,uint32_t,uint32_t,rk_aiq_working_mode_t) { _exit(92); }
extern "C" XCamReturn rk_aiq_uapi2_sysctl_start(const rk_aiq_sys_ctx_t* c) { if(!c) _exit(93); return scenario==2?XCAM_RETURN_ERROR_FAILED:XCAM_RETURN_NO_ERROR; }
int main() {
 for(scenario=0;scenario<4;scenario++) {
  pid_t child=fork(); if(child<0)return 2;
  if(!child) { rkaiq_media_info m={};
   if(scenario==0)init_engine(&m);
   else { if(scenario>=2)m.aiq_ctx=reinterpret_cast<rk_aiq_sys_ctx_t*>(1);start_engine(&m); }
   _exit(0);
  }
  int status;waitpid(child,&status,0);int expected=scenario==3?0:EXIT_FAILURE;
  if(!WIFEXITED(status)||WEXITSTATUS(status)!=expected){fprintf(stderr,"scenario %d failed status=%d\n",scenario,status);return 1;}
 }
 puts("PASS: init failure, null start, failed start, successful start");return 0;
}
