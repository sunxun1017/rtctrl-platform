/* Local experiment linked against the matching board RKAIQ. */
#include <stdio.h>
#include <dlfcn.h>
#include <stdlib.h>
#include <unistd.h>
#include <signal.h>
#include "uAPI2/rk_aiq_user_api2_ae.h"
#include "uAPI2/rk_aiq_user_api2_awb.h"
#include "uAPI2/rk_aiq_user_api2_sysctl.h"
static volatile sig_atomic_t done;
static void watchdog(int sig) { (void)sig; const char m[]="LIFECYCLE_TIMEOUT\n"; write(2,m,sizeof(m)-1); _exit(124); }
static void on_signal(int sig) { (void)sig; done=1; }
int main(int argc, char **argv) {
    setvbuf(stdout,NULL,_IONBF,0);
    if (argc != 4) { fprintf(stderr,"usage: %s SENSOR_ENTITY IQ_DIRECTORY SECONDS\n",argv[0]); return 2; }
    void *lib=dlopen("librkaiq.so",RTLD_NOW|RTLD_LOCAL);
    if (!lib) { fprintf(stderr,"%s\n",dlerror()); return 7; }
    __typeof__(&rk_aiq_uapi2_sysctl_init) p_rk_aiq_uapi2_sysctl_init=dlsym(lib,"rk_aiq_uapi2_sysctl_init");
    if (!p_rk_aiq_uapi2_sysctl_init) return 7;
    __typeof__(&rk_aiq_uapi2_sysctl_setListenStrmStatus) p_rk_aiq_uapi2_sysctl_setListenStrmStatus=dlsym(lib,"rk_aiq_uapi2_sysctl_setListenStrmStatus");
    if (!p_rk_aiq_uapi2_sysctl_setListenStrmStatus) return 7;
    __typeof__(&rk_aiq_uapi2_sysctl_prepare) p_rk_aiq_uapi2_sysctl_prepare=dlsym(lib,"rk_aiq_uapi2_sysctl_prepare");
    if (!p_rk_aiq_uapi2_sysctl_prepare) return 7;
    __typeof__(&rk_aiq_uapi2_sysctl_start) p_rk_aiq_uapi2_sysctl_start=dlsym(lib,"rk_aiq_uapi2_sysctl_start");
    if (!p_rk_aiq_uapi2_sysctl_start) return 7;
    __typeof__(&rk_aiq_uapi2_sysctl_stop) p_rk_aiq_uapi2_sysctl_stop=dlsym(lib,"rk_aiq_uapi2_sysctl_stop");
    if (!p_rk_aiq_uapi2_sysctl_stop) return 7;
    __typeof__(&rk_aiq_uapi2_sysctl_deinit) p_rk_aiq_uapi2_sysctl_deinit=dlsym(lib,"rk_aiq_uapi2_sysctl_deinit");
    if (!p_rk_aiq_uapi2_sysctl_deinit) return 7;
    __typeof__(&rk_aiq_user_api2_ae_queryExpResInfo) queryAE=dlsym(lib,"rk_aiq_user_api2_ae_queryExpResInfo");
    __typeof__(&rk_aiq_user_api2_awb_QueryWBInfo) queryWB=dlsym(lib,"rk_aiq_user_api2_awb_QueryWBInfo");
    __typeof__(&rk_aiq_user_api2_awb_getStrategyResult) queryStrategy=dlsym(lib,"rk_aiq_user_api2_awb_getStrategyResult");
    int seconds=atoi(argv[3]);
    if (seconds<1 || seconds>3600) return 2;
    signal(SIGTERM,on_signal); signal(SIGINT,on_signal);
    rk_aiq_sys_ctx_t *ctx=p_rk_aiq_uapi2_sysctl_init(argv[1],argv[2],NULL,NULL);
    if (!ctx) { fprintf(stderr,"INIT_FAILED\n"); return 3; }
    p_rk_aiq_uapi2_sysctl_setListenStrmStatus(ctx,true);
    int ret=p_rk_aiq_uapi2_sysctl_prepare(ctx,2112,1568,RK_AIQ_WORKING_MODE_NORMAL);
    printf("PREPARE=%d\n",ret); fflush(stdout);
    if (ret) { p_rk_aiq_uapi2_sysctl_deinit(ctx); return 4; }
    ret=p_rk_aiq_uapi2_sysctl_start(ctx);
    printf("START=%d\n",ret); fflush(stdout);
    if (ret) { p_rk_aiq_uapi2_sysctl_deinit(ctx); return 5; }
    while (seconds-- && !done) {
        sleep(1);
        ae_api_queryInfo_t ae={0}; rk_aiq_wb_querry_info_t wb={0};
        if(queryAE) { int q=queryAE(ctx,&ae); printf("AE_QUERY=%d pclk=%.6f hts=%.0f vts=%.0f fps=%.3f converged=%d mean=%.3f\n",q,ae.pclk,ae.hts,ae.vts,ae.fps,ae.isConverged,ae.linExpInfo.meanLuma); }
        if(queryStrategy) { rk_tool_awb_strategy_result_t st={0}; int q=queryStrategy(ctx,&st);
            printf("AWB_STRATEGY=%d count=%u whitepoints=%u nor=%.5f big=%.5f lights=%d method=%d preclip=%.5f,%.5f clipped=%.5f,%.5f adjusted=%.5f,%.5f\n",q,st.count,st.WPTotalNUM,st.wpNorNumRat,st.wpBigNumRat,st.lightNum,st.gnCalc_method,st.wbGainIntpStrategy[0],st.wbGainIntpStrategy[3],st.wbGainClip[0],st.wbGainClip[3],st.wbGainAdjust[0],st.wbGainAdjust[3]); }
        if(queryWB) { int q=queryWB(ctx,&wb); printf("WB_QUERY=%d gains=%.5f,%.5f,%.5f,%.5f converged=%d mode=%d\n",q,wb.gain.rgain,wb.gain.grgain,wb.gain.gbgain,wb.gain.bgain,wb.awbConverged,wb.opMode); }
    }
    signal(SIGALRM,watchdog); alarm(10);
    printf("STOP_BEGIN\n");
    ret=p_rk_aiq_uapi2_sysctl_stop(ctx,false);
    printf("STOP=%d\n",ret);
    printf("DEINIT_BEGIN\n");
    p_rk_aiq_uapi2_sysctl_deinit(ctx);
    alarm(0);
    printf("DEINIT_DONE\n");
    return ret ? 6 : 0;
}
