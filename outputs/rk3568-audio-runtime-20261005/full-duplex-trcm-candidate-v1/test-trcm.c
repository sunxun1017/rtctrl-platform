/* Actual PCM/C3/CPU bodies plus an explicit native unlinked action slice. */
static struct snd_pcm_mmap_status native_status[2];
static pthread_mutex_t cut_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cut_cond = PTHREAD_COND_INITIALIZER;
static bool cut_post, cut_ready, cut_release, cut_done, irq_attempt;
static bool GO_fault;
static unsigned int xrun_calls[2], xrun_saw_running[2];
static const struct snd_pcm_ops native_pcm_ops = {.trigger=soc_pcm_trigger};
static unsigned int ticket_borrows(void)
{
#if TRCM_CANDIDATE
    return info.starting;
#else
    return 0; /* Baseline has no CPU ticket state, not a fabricated implementation. */
#endif
}
static void trcm_native_cut(void *function)
{
    if (function != (void *)snd_pcm_post_start || !cut_post) return;
    pthread_mutex_lock(&cut_lock);
    cut_ready = true; pthread_cond_broadcast(&cut_cond);
    while (!cut_release) pthread_cond_wait(&cut_cond,&cut_lock);
    pthread_mutex_unlock(&cut_lock);
}
static int snd_pcm_stop_xrun(struct snd_pcm_substream *ss)
{
    /* Actual native lock contract model: IRQ may wait for post_start publication. */
    pthread_mutex_lock(&cut_lock); irq_attempt = true; pthread_cond_broadcast(&cut_cond); pthread_mutex_unlock(&cut_lock);
    snd_pcm_stream_lock_irq(ss);
    xrun_calls[ss->stream]++;
    if (ss->runtime->status->state == SNDRV_PCM_STATE_RUNNING) {
        xrun_saw_running[ss->stream]++;
        soc_pcm_trigger(ss,SNDRV_PCM_TRIGGER_STOP);
        ss->runtime->status->state = SNDRV_PCM_STATE_XRUN; /* XRUN API boundary. */
    }
    snd_pcm_stream_unlock_irq(ss);
    return 0;
}
static void trcm_GO_cut(struct snd_pcm_substream *ss)
{
    if(seam_at_GO) {
        seam_at_GO=false;
        seam_check_result=dmaengine_pcm_check_fault(ss);
        seam_borrow_after_notify=ticket_borrows();
        seam_cached_error=-EREMOTEIO;
        seam_check_result=dmaengine_pcm_check_fault(ss);
        return;
    }
    if (!GO_fault) return;
    GO_fault=false;
    /* Precisely named CPU fault sink at an admitted but not committed DMA API cut. */
    if (cpu_driver.ops->pcm_async_fault) cpu_driver.ops->pcm_async_fault(&cpu_dai,-EIO);
}
static void trcm_setup(void)
{
    shared_setup();
    boundary("TRCM_actual_two_params_and_owner_prepare", configure_both());
    memset(native_status,0,sizeof(native_status));memset(xrun_calls,0,sizeof(xrun_calls));memset(xrun_saw_running,0,sizeof(xrun_saw_running));
    cut_post=cut_ready=cut_release=cut_done=irq_attempt=GO_fault=false;
    for (int i=0;i<2;i++) {
        substreams[i].ops=&native_pcm_ops;
        runtimes[i].status=&native_status[i];runtimes[i].rate=48000;runtimes[i].buffer_size=256;
        native_status[i].state=SNDRV_PCM_STATE_PREPARED;
    }
    params_clear_events();
}
static void trcm_seq(int first)
{
    trcm_setup();char name[100];
    int r0=snd_pcm_start_lock_irq(&substreams[first]);
    int r1=snd_pcm_start_lock_irq(&substreams[!first]);
    snprintf(name,sizeof(name),"sequential_first_%d_second_normal_START",first);
    contract(name,r0==0 && r1==0 && info.started==3 && dma_running[0] && dma_running[1]);
    boundary("TRCM_second_START_keeps_shared_XFER_and_both_DMA",r0==0 && r1==0 && !ticket_borrows() &&
        !info.runtime_error && map.hw[I2S_XFER/4]==(I2S_XFER_TXS_START|I2S_XFER_RXS_START));
    unsigned int oldxfer=map.hw[I2S_XFER/4];
    boundary("TRCM_direction_STOP_keeps_peer_and_global_transport",soc_pcm_trigger(&substreams[first],SNDRV_PCM_TRIGGER_STOP)==0 &&
        info.started==BIT(!first) && !dma_running[first] && dma_running[!first] && map.hw[I2S_XFER/4]==oldxfer && !info.stop_proven);
    boundary("TRCM_prepare_with_active_peer_does_not_global_STOP",i2s_checked_prepare(&substreams[first],&cpu_dai)==0 &&
        info.started==BIT(!first) && map.hw[I2S_XFER/4]==oldxfer && !info.runtime_error);
    boundary("TRCM_stopped_owner_can_restart_without_peer_clock_reset",soc_pcm_trigger(&substreams[first],SNDRV_PCM_TRIGGER_START)==0 && info.started==3);
    soc_pcm_trigger(&substreams[first],SNDRV_PCM_TRIGGER_STOP);
    boundary("TRCM_close_idle_direction_preserves_peer_owner_cache",soc_pcm_hw_free(&substreams[first])==0 && soc_pcm_clean(&substreams[first],0)==0 &&
        info.started==BIT(!first) && info.substreams[!first]==&substreams[!first] && shared_caches(48000) && dma_running[!first]);
    boundary("TRCM_last_STOP_gets_direct_global_proof",soc_pcm_trigger(&substreams[!first],SNDRV_PCM_TRIGGER_STOP)==0 && !info.started &&
        info.stop_proven && !map.hw[I2S_XFER/4] && !(map.hw[I2S_DMACR/4]&(I2S_DMACR_TDE_MASK|I2S_DMACR_RDE_MASK)));
    soc_pcm_hw_free(&substreams[!first]);soc_pcm_clean(&substreams[!first],0);
    params_dump(name);
}
static void trcm_concurrent(void)
{
    trcm_setup();pthread_t threads[2];struct concurrent_arg args[2]={{0,777},{1,777}};
    pthread_barrier_init(&dma_barrier,NULL,2);concurrent_cut=true;
    if (pthread_create(&threads[0],NULL,start_thread,&args[0]) || pthread_create(&threads[1],NULL,start_thread,&args[1])) exit(2);
    pthread_join(threads[0],NULL);pthread_join(threads[1],NULL);concurrent_cut=false;pthread_barrier_destroy(&dma_barrier);
    contract("concurrent_two_normal_START_commit_both",args[0].result==0 && args[1].result==0 && info.started==3 && dma_running[0] && dma_running[1]);
    boundary("TRCM_two_component_tickets_commit_without_loser_rollback",args[0].result==0 && args[1].result==0 && !ticket_borrows() &&
        dma_go[0]==1 && dma_go[1]==1 && !dma_stop[0] && !dma_stop[1] && !info.runtime_error);
    soc_pcm_trigger(&substreams[0],SNDRV_PCM_TRIGGER_STOP);soc_pcm_trigger(&substreams[1],SNDRV_PCM_TRIGGER_STOP);
    boundary("TRCM_concurrent_START_final_STOP_proof",!info.started && info.stop_proven && !dma_running[0] && !dma_running[1]);
    /* Concurrent event order is intentionally not claimed deterministic; observations follow join. */
    params_clear_events();params_dump("TRCM_concurrent_START_observations_only");
}
static void trcm_joint(void)
{
    trcm_setup();snd_pcm_start_lock_irq(&substreams[0]);snd_pcm_start_lock_irq(&substreams[1]);
    fault_at=operations+1;
    irqreturn_t r=i2s_checked_isr(&info);fault_at=0;
    contract("shared_fault_joint_STOP_reaches_global_proof",r==IRQ_HANDLED && xrun_calls[0]==1 && xrun_calls[1]==1 && info.runtime_error==-EREMOTEIO && !info.started &&
        info.stop_proven && !map.hw[I2S_XFER/4] && !(map.hw[I2S_DMACR/4]&(I2S_DMACR_TDE_MASK|I2S_DMACR_RDE_MASK)));
    boundary("TRCM_status_IO_error_notifies_both_and_keeps_first_errno",xrun_calls[0]==1 && xrun_calls[1]==1 && info.runtime_error==-EREMOTEIO);
    boundary("TRCM_fault_blocks_NEW_START_before_DMA",soc_pcm_trigger(&substreams[0],SNDRV_PCM_TRIGGER_START)==-EREMOTEIO && !ticket_borrows());
    params_dump("TRCM_shared_status_IO_error");
}
static void trcm_ticket_window(void)
{
    trcm_setup();GO_fault=true;int r=soc_pcm_trigger(&substreams[0],SNDRV_PCM_TRIGGER_START);
    boundary("TRCM_async_sink_invalidates_admitted_ticket_before_DAI_commit",r==-EIO && info.runtime_error==-EIO && !info.started && !ticket_borrows());
    boundary("TRCM_failed_commit_C3_returns_DMA_borrow_and_STOP_proof",dma_go[0]==1 && dma_stop[0]==1 && !dma_running[0] && info.stop_proven && !info.started);
    params_dump("TRCM_fault_during_GO_API");
}
static void trcm_admission_and_rollback(void)
{
    trcm_setup();params_inject_start_error=true;int r=soc_pcm_trigger(&substreams[0],SNDRV_PCM_TRIGGER_START);
    boundary("TRCM_shared_CPU_write_error_keeps_first_errno_and_C3_prefix",r==-EREMOTEIO && info.runtime_error==-EREMOTEIO &&
        !ticket_borrows() && dma_go[0]==1 && dma_stop[0]==1 && !dma_running[0] && !info.started);
    params_dump("TRCM_CPU_commit_IO_error");
    trcm_setup();boundary("TRCM_wrong_SS_ticket_admission_rejects_before_DMA",i2s_checked_component_trigger(&cpu_component,&(struct snd_pcm_substream){.stream=0},SNDRV_PCM_TRIGGER_START)==-EINVAL && !dma_go[0]);
    int admitted=i2s_checked_component_trigger(&cpu_component,&substreams[0],SNDRV_PCM_TRIGGER_START);
    unsigned int oldops=operations;
    boundary("TRCM_reserved_owner_rejects_HW_FREE_prepare_and_PM_without_mutation",admitted==0 && ticket_borrows()==BIT(0) &&
        soc_pcm_hw_free(&substreams[0])==-EBUSY && i2s_checked_prepare(&substreams[1],&cpu_dai)==-EBUSY &&
        i2s_checked_runtime_suspend(&info)==-EBUSY && operations==oldops && shared_caches(48000));
    i2s_checked_component_trigger(&cpu_component,&substreams[0],SNDRV_PCM_TRIGGER_STOP);
    boundary("TRCM_cancelled_ticket_cannot_commit_stale_DAI",rockchip_i2s_tdm_trigger(&substreams[0],SNDRV_PCM_TRIGGER_START,&cpu_dai)==-EINVAL && !ticket_borrows() && !info.started);
    params_dump("TRCM_reservation_and_stale_commit");
}
struct native_start_arg {int result;};
static void *native_start_thread(void *data)
{
    struct native_start_arg *a=data;a->result=snd_pcm_start_lock_irq(&substreams[0]);
    pthread_mutex_lock(&cut_lock);cut_done=true;pthread_cond_broadcast(&cut_cond);pthread_mutex_unlock(&cut_lock);return NULL;
}
static void *irq_thread(void *data) { (void)data;i2s_checked_isr(&info);return NULL; }
static void trcm_native_window(void)
{
    trcm_setup();boundary("TRCM_native_peer_actual_do_post_START",snd_pcm_start_lock_irq(&substreams[1])==0);
    pthread_t t,irq;struct native_start_arg a={777};cut_post=true;
    if (pthread_create(&t,NULL,native_start_thread,&a))exit(2);
    pthread_mutex_lock(&cut_lock);while(!cut_ready && !cut_done)pthread_cond_wait(&cut_cond,&cut_lock);bool reached=cut_ready;pthread_mutex_unlock(&cut_lock);
    bool waiting=false;
    if(reached) {
        map.cache[I2S_INTSR/4]=map.hw[I2S_INTSR/4]=I2S_INTSR_TXUI_ACT;
        if(pthread_create(&irq,NULL,irq_thread,NULL))exit(2);
        pthread_mutex_lock(&cut_lock);while(!irq_attempt)pthread_cond_wait(&cut_cond,&cut_lock);
        waiting=native_status[0].state==SNDRV_PCM_STATE_PREPARED && !xrun_calls[0];
        cut_release=true;pthread_cond_broadcast(&cut_cond);pthread_mutex_unlock(&cut_lock);
        pthread_join(irq,NULL);
    }
    pthread_join(t,NULL);cut_post=false;
    boundary("TRCM_IRQ_capture_before_real_native_post_waits_stream_lock",reached && waiting && a.result==0 && xrun_saw_running[0]==1);
    boundary("TRCM_health_single_IRQ_XRUN_preserves_peer_without_sticky",reached && xrun_calls[0]==1 && !xrun_calls[1] &&
        info.started==BIT(1) && dma_running[1] && !dma_running[0] && !info.runtime_error && !info.stop_proven);
    soc_pcm_trigger(&substreams[1],SNDRV_PCM_TRIGGER_STOP);
    params_clear_events();params_dump("TRCM_native_post_IRQ_observations_only");
}
static void trcm_sink_without_access(bool transition)
{
    trcm_setup();boundary("TRCM_sink_PM_cut_after_real_START",soc_pcm_trigger(&substreams[0],SNDRV_PCM_TRIGGER_START)==0);
    unsigned int oldops=operations, oldxfer=map.hw[I2S_XFER/4];
    if(transition)info.power_transition=true;else info.mclks_enabled=false;
    if(cpu_driver.ops->pcm_async_fault)cpu_driver.ops->pcm_async_fault(&cpu_dai,-EIO);
    boundary("TRCM_sink_without_access_closes_gate_zero_MMIO_retains_unproved_transport",operations==oldops &&
        info.runtime_error==-EIO && info.started==BIT(0) && !info.stop_proven && map.hw[I2S_XFER/4]==oldxfer);
    info.power_transition=false;info.mclks_enabled=true;
    if(cpu_driver.ops->pcm_async_fault)cpu_driver.ops->pcm_async_fault(&cpu_dai,-ENOSPC);
    boundary("TRCM_sink_later_live_STOP_keeps_first_errno",info.runtime_error==-EIO && !info.started && info.stop_proven && !map.hw[I2S_XFER/4]);
    params_dump(transition?"TRCM_sink_during_PM_transition":"TRCM_sink_without_clocks");
}
static void trcm_actual_DMA_seam(void)
{
    trcm_setup();
    struct dmaengine_pcm_runtime_data prtd={.dma_chan=&params_channels_dma[0],.checked=true,
        .error_sink=dmaengine_pcm_cpu_fault,.error_sink_arg=&cpu_dai};
    pthread_mutex_init(&prtd.lifecycle_lock,NULL);runtimes[0].private_data=&prtd;
    seam_cached_checks=seam_borrow_after_notify=0;seam_cached_error=-ENOSPC;seam_check_result=777;seam_at_GO=true;
    int ret=soc_pcm_trigger(&substreams[0],SNDRV_PCM_TRIGGER_START);
    boundary("TRCM_actual_DMA_check_notify_bridge_closes_CPU_before_DAI_commit",ret==-ENOSPC && seam_cached_checks==2 &&
        seam_check_result==-ENOSPC && prtd.first_error==-ENOSPC && info.runtime_error==-ENOSPC);
    boundary("TRCM_actual_DMA_notify_revokes_ticket_but_keeps_GO_borrow_until_C3_STOP",seam_borrow_after_notify==BIT(0) &&
        !ticket_borrows() && !info.started && dma_go[0]==1 && dma_stop[0]==1 && !dma_running[0] && info.stop_proven);
    boundary("TRCM_actual_sync_DMA_notify_does_not_fake_PREPARED_XRUN_drain",!xrun_calls[0] && !xrun_calls[1] && native_status[0].state==SNDRV_PCM_STATE_PREPARED);
    runtimes[0].private_data=NULL;pthread_mutex_destroy(&prtd.lifecycle_lock);
    params_dump("TRCM_actual_DMA_CPU_seam");
}
int main(void)
{
    for(int d=0;d<2;d++){shared_peer_failure(d,false);shared_peer_failure(d,true);shared_two_free(d);shared_running(d);}
    trcm_seq(0);trcm_seq(1);trcm_concurrent();trcm_joint();trcm_ticket_window();trcm_admission_and_rollback();trcm_native_window();
    trcm_sink_without_access(false);trcm_sink_without_access(true);
    trcm_actual_DMA_seam();
    printf("{\"contract_total\":%u,\"contract_passed\":%u,\"boundary_total\":%u,\"boundary_passed\":%u}\n",contract_total,contract_passed,boundary_total,boundary_passed);
    return contract_passed==contract_total && boundary_passed==boundary_total ? 0 : 1;
}
