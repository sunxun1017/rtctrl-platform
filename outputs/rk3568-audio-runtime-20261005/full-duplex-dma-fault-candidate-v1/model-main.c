struct fixture {
    struct device device; struct pl330_dmac controller; struct dma_pl330_chan pch[2];
    struct pl330_thread thread[2],manager; struct dma_pl330_desc desc[2];
    struct snd_card card; struct snd_pcm pcm; struct snd_pcm_runtime runtime[2];
    struct snd_pcm_substream ss[2]; struct dmaengine_pcm_runtime_data prtd[2];
    int cpu_error,cpu_stop,ticket_epoch,starting_epoch; bool stop_peer_on_sink;
};
static int failures,observations;
static atomic_bool pause_sink, sink_waiting, allow_sink, sync_started, sync_done;
static void observe(const char *n,bool ok) { printf("OBS %s %d\n",n,ok); observations++; if(!ok)failures++; }
static void cpu_sink(struct snd_pcm_substream *s,int error,void *arg) {
    struct fixture *f=arg; assert(!spin_depth); s->sink_calls++;
    if(!f->cpu_error)f->cpu_error=error;
    f->ticket_epoch++; f->cpu_stop++;
    if(atomic_load(&pause_sink)&&s->index==0){atomic_store(&sink_waiting,true);while(!atomic_load(&allow_sink))usleep(1000);}
    if(f->stop_peer_on_sink){pl330_terminate_channel(&f->pch[0].chan);pl330_terminate_channel(&f->pch[1].chan);}
}
static void result_callback(void *arg,const struct dmaengine_result *r) {
#if CANDIDATE
    dmaengine_pcm_dma_complete_result(arg,r);
#else
    (void)r; dmaengine_pcm_dma_complete(arg);
#endif
}
static void setup(struct fixture *f) {
    memset(f,0,sizeof(*f)); struct pl330_dmac *d=&f->controller;
    pthread_mutex_init(&d->lock.value,NULL); d->base=d->registers; d->state=INIT;
    d->num_peripherals=d->pcfg.num_chan=2; d->peripherals=f->pch;
    d->channels=f->thread; d->manager=&f->manager; d->ddma.dev=&f->device;
    mutex_init(&f->card.memory_mutex); f->pcm.card=&f->card; f->card.total_pcm_alloc_bytes=128;
    for(int i=0;i<2;i++){
        struct dma_pl330_chan *p=&f->pch[i]; struct dma_pl330_desc *x=&f->desc[i];
        pthread_mutex_init(&p->lock.value,NULL); mutex_init(&p->sync_mutex);
        p->dmac=d; p->chan.device=&d->ddma; p->thread=&f->thread[i]; p->epoch=10+i;
        p->thread->state=1; p->thread->owner_pch=p; p->thread->accept_callbacks=true;
        INIT_LIST_HEAD(&p->work_list); INIT_LIST_HEAD(&p->submitted_list); INIT_LIST_HEAD(&p->retired_list);
        INIT_LIST_HEAD(&x->node); x->owner_pch=p; x->owner_epoch=p->epoch; atomic_store(&x->refs.value,1);
        p->model_desc=x;
        x->txd.callback_result=result_callback; x->txd.callback_param=&f->ss[i]; list_add_tail(&x->node,&p->work_list);
        struct snd_pcm_substream *s=&f->ss[i]; struct snd_pcm_runtime *r=&f->runtime[i];
        s->runtime=r; s->pcm=&f->pcm; s->state=2; s->index=i; pthread_mutex_init(&s->stream_lock.value,NULL);
        s->dma_buffer.dev.type=SNDRV_DMA_TYPE_DEV; s->dma_buffer.dev.dev=&f->device;
        s->dma_buffer.area=calloc(1,64); s->dma_buffer.addr=(uintptr_t)s->dma_buffer.area; s->dma_buffer.bytes=64;
        snd_pcm_set_runtime_buffer(s,&s->dma_buffer);
        struct dmaengine_pcm_runtime_data *pr=&f->prtd[i]; r->private_data=pr;
        pr->dma_chan=&p->chan; pr->checked=true; pr->cookie=1; pthread_mutex_init(&pr->lifecycle_lock.value,NULL);
        mutex_init(&pr->quiesce_mutex); pr->quarantine=snd_pcm_dma_quarantine_alloc(); pr->owner_buffer=&s->dma_buffer;
        pr->owner=s->dma_buffer;
#if CANDIDATE
        assert(snd_dmaengine_pcm_set_error_sink(s,cpu_sink,f)==0);
#endif
        pr->exposed=true;
    }
}
static void cleanup(struct fixture *f) {
    for(int i=0;i<2;i++){
        struct dmaengine_pcm_runtime_data *p=&f->prtd[i];
        if(p->quarantine->consumed){list_del_init(&p->quarantine->node);free(p->quarantine->saved.area);free(p->quarantine);}
        else {free(f->ss[i].dma_buffer.area);snd_pcm_dma_quarantine_free(p->quarantine);}
        pthread_mutex_destroy(&f->pch[i].lock.value);
        pthread_mutex_destroy(&f->pch[i].sync_mutex.value);
        pthread_mutex_destroy(&p->lifecycle_lock.value);
        pthread_mutex_destroy(&p->quiesce_mutex.value);
        pthread_mutex_destroy(&f->ss[i].stream_lock.value);
    }
    pthread_mutex_destroy(&f->controller.lock.value);
    pthread_mutex_destroy(&f->card.memory_mutex.value);
}
static void publish(struct fixture *f,int error) {
    unsigned long flags; spin_lock_irqsave(&f->controller.lock,flags);
    pl330_error_locked(&f->controller,error); spin_unlock_irqrestore(&f->controller.lock,flags);
}
static void dispatch(struct fixture *f) {
    if(f->controller.tasks.queued){f->controller.tasks.queued=false;pl330_dotask(&f->controller.tasks);}
}
static void start_fixture(struct fixture *f) {
    setup(f); f->prtd[0].exposed=false; f->ss[0].state=1; submit_chan=&f->pch[0].chan;
    f->starting_epoch=f->ticket_epoch;
}
static void *notify_thread(void *arg) { dispatch(arg); return NULL; }
static int joined_sync_result;
static void *sync_thread(void *arg) { struct fixture *f=arg; atomic_store(&sync_started,true); joined_sync_result=pl330_sync_channel(&f->pch[1].chan,true); atomic_store(&sync_done,true); return NULL; }
static void dai_fault(struct snd_soc_dai *d,int error) { cpu_sink(d->model_ss,error,d->model_arg); }
int main(void) {
    struct fixture f; struct dmaengine_result error={.result=DMA_TRANS_ABORTED};
    setup(&f); publish(&f,-ETIMEDOUT); publish(&f,-EIO); dispatch(&f);
    observe("first-controller-errno",f.controller.lifecycle_error==-ETIMEDOUT);
    observe("two-stream-xrun-no-peer-period",f.ss[0].xruns==1&&f.ss[1].xruns==1&&f.ss[0].periods==0&&f.ss[1].periods==0);
    observe("two-pcm-exact-first-errno",f.prtd[0].first_error==-ETIMEDOUT&&f.prtd[1].first_error==-ETIMEDOUT);
    observe("cpu-admission-before-xrun",f.cpu_error==-ETIMEDOUT&&f.cpu_stop==2);
    observe("callbacks-drained",!atomic_read(&f.pch[0].producers)&&!atomic_read(&f.pch[1].producers));
    cleanup(&f);
    setup(&f); f.stop_peer_on_sink=true; publish(&f,-ENOSPC); dispatch(&f);
    observe("capture-both-before-joint-stop",f.ss[0].xruns==1&&f.ss[1].xruns==1);
    observe("captured-callback-not-new-epoch",f.ss[0].sink_calls==1&&f.ss[1].sink_calls==1);
    cleanup(&f);
    setup(&f); pl330_terminate_channel(&f.pch[0].chan); publish(&f,-EIO); dispatch(&f);
    observe("cutoff-first-skip-old-channel",f.ss[0].xruns==0&&f.ss[1].xruns==1);
    cleanup(&f);
    setup(&f); result_callback(&f.ss[0],&error);
    observe("error-result-no-pos-no-period",f.prtd[0].pos==0&&f.ss[0].periods==0);
    observe("missing-provider-errno-fallback",f.prtd[0].first_error==-EIO);
    cleanup(&f);
    setup(&f); struct dmaengine_result healthy={.result=DMA_TRANS_NOERROR}; result_callback(&f.ss[0],&healthy);
    observe("healthy-period-original-path",f.prtd[0].pos==16&&f.ss[0].periods==1&&f.ss[0].xruns==0);
    cleanup(&f);
    setup(&f); publish(&f,-EREMOTEIO);
    observe("pointer-error-xrun-sentinel",snd_dmaengine_pcm_pointer(&f.ss[0])==SNDRV_PCM_POS_XRUN);
    observe("no-residue-error-xrun-sentinel",snd_dmaengine_pcm_pointer_no_residue(&f.ss[1])==SNDRV_PCM_POS_XRUN);
    cleanup(&f);
    setup(&f); int ret=pl330_sync_channel(&f.pch[0].chan,true);
    observe("healthy-own-stop-peer-running",ret==0&&!f.pch[0].quiescing&&f.thread[1].state==1&&!f.controller.stop_proven);
    cleanup(&f);
    setup(&f); publish(&f,-ETIMEDOUT); dispatch(&f);
    int r0=snd_dmaengine_pcm_quiesce(&f.ss[0]); int r1=snd_dmaengine_pcm_quiesce(&f.ss[1]);
    observe("two-separate-quarantines",r0==-ETIMEDOUT&&r1==-ETIMEDOUT&&f.prtd[0].quarantine->consumed&&f.prtd[1].quarantine->consumed&&f.prtd[0].quarantine!=f.prtd[1].quarantine);
    observe("two-allocation-accounting",f.card.total_pcm_alloc_bytes==0&&f.ss[0].runtime->dma_buffer_p==NULL&&f.ss[1].runtime->dma_buffer_p==NULL);
    cleanup(&f);
#if CANDIDATE
    setup(&f); list_del_init(&f.desc[0].node); f.ss[0].state=1; f.starting_epoch=f.ticket_epoch;
    publish(&f,-EPIPE); int before=f.ss[0].xruns; ret=dmaengine_pcm_check_fault(&f.ss[0]);
    observe("prepared-no-descriptor-exact-probe",ret==-EPIPE&&f.cpu_error==-EPIPE&&f.ticket_epoch!=f.starting_epoch);
    observe("prepared-probe-no-recursive-xrun",f.ss[0].xruns==before);
    cleanup(&f);
#else
    observe("prepared-no-descriptor-exact-probe",false);
    observe("prepared-probe-no-recursive-xrun",false);
#endif
    start_fixture(&f); inject_go_errno=-ETIMEDOUT; ret=snd_dmaengine_pcm_trigger(&f.ss[0],SNDRV_PCM_TRIGGER_START);
    observe("go-error-exact-sticky",ret==-ETIMEDOUT&&f.prtd[0].first_error==-ETIMEDOUT&&f.pch[0].go_calls==1);
    observe("go-before-commit-ticket-invalidated",f.cpu_error==-ETIMEDOUT&&f.ticket_epoch!=f.starting_epoch&&f.ss[0].xruns==0);
    cleanup(&f);
    start_fixture(&f); inject_status_errno=-EREMOTEIO; ret=snd_dmaengine_pcm_trigger(&f.ss[0],SNDRV_PCM_TRIGGER_START);
    observe("status-new-fault-after-go-probe",ret==-EREMOTEIO&&f.prtd[0].first_error==-EREMOTEIO&&f.pch[0].go_calls==1);
    cleanup(&f);
    setup(&f); inject_status_errno=-ENOSPC;
    observe("pointer-status-new-exact-fault",snd_dmaengine_pcm_pointer(&f.ss[0])==SNDRV_PCM_POS_XRUN&&f.prtd[0].first_error==-ENOSPC);
    cleanup(&f);
    start_fixture(&f); inject_prepare_errno=-ETIMEDOUT; ret=snd_dmaengine_pcm_trigger(&f.ss[0],SNDRV_PCM_TRIGGER_START);
    observe("prepare-null-exact-no-go",ret==-ETIMEDOUT&&f.cpu_error==-ETIMEDOUT&&f.pch[0].go_calls==0);
    cleanup(&f);
    start_fixture(&f); inject_submit_errno=-EREMOTEIO; ret=snd_dmaengine_pcm_trigger(&f.ss[0],SNDRV_PCM_TRIGGER_START);
    observe("submit-error-exact-no-go",ret==-EREMOTEIO&&f.cpu_error==-EREMOTEIO&&f.pch[0].go_calls==0);
    cleanup(&f);
    start_fixture(&f); publish(&f,-EPIPE); ret=snd_dmaengine_pcm_trigger(&f.ss[0],SNDRV_PCM_TRIGGER_START);
    observe("prepared-start-cache-fault-no-go",ret==-EPIPE&&f.cpu_error==-EPIPE&&f.pch[0].go_calls==0);
    cleanup(&f);
    setup(&f); list_del_init(&f.desc[0].node); f.ss[0].state=1; publish(&f,-ETIMEDOUT);
    ret=snd_dmaengine_pcm_quiesce(&f.ss[0]);
    observe("prepare-quiesce-no-desc-closes-cpu",ret==-ETIMEDOUT&&f.cpu_error==-ETIMEDOUT&&f.ss[0].xruns==0);
    cleanup(&f);
#if CANDIDATE
    setup(&f); publish(&f,-ETIMEDOUT); atomic_store(&pause_sink,true);
    atomic_store(&sink_waiting,false); atomic_store(&allow_sink,false); atomic_store(&sync_started,false); atomic_store(&sync_done,false);
    pthread_t notifier,syncer; pthread_create(&notifier,NULL,notify_thread,&f);
    while(!atomic_load(&sink_waiting))usleep(1000);
    pthread_create(&syncer,NULL,sync_thread,&f);
    while(!atomic_load(&sync_started))usleep(1000);
    for(;;){unsigned long flags;spin_lock_irqsave(&f.pch[1].lock,flags);bool cut=f.pch[1].quiescing;spin_unlock_irqrestore(&f.pch[1].lock,flags);if(cut)break;usleep(1000);}
    observe("borrow-first-close-sync-waits",atomic_read(&f.pch[1].producers)==1&&!atomic_load(&sync_done));
    atomic_store(&allow_sink,true); pthread_join(notifier,NULL); pthread_join(syncer,NULL); atomic_store(&pause_sink,false);
    observe("borrow-drain-after-callback",joined_sync_result==-ETIMEDOUT&&!atomic_read(&f.pch[1].producers)&&f.ss[1].xruns==1);
    cleanup(&f);
#else
    observe("borrow-first-close-sync-waits",false);
    observe("borrow-drain-after-callback",false);
#endif
    setup(&f);
    struct snd_soc_dai_ops dai_ops={.pcm_async_fault=dai_fault};
    struct snd_soc_dai_driver dai_driver={.ops=&dai_ops};
    struct snd_soc_dai dai={.driver=&dai_driver,.model_arg=&f,.model_ss=&f.ss[0]};
    struct snd_soc_pcm_runtime rtd={.num_cpus=1,.dais={&dai,NULL}};
    struct dmaengine_pcm pcm={.chan={&f.pch[0].chan,&f.pch[1].chan}};
    struct snd_soc_component component={.pcm=&pcm}; f.ss[0].private_data=&rtd;
#if CANDIDATE
    f.prtd[0].error_sink=NULL;f.prtd[0].error_sink_arg=NULL;
#endif
    f.prtd[0].exposed=false; ret=dmaengine_pcm_open(&component,&f.ss[0]);
    publish(&f,-ETIMEDOUT);result_callback(&f.ss[0],&error);
    observe("generic-real-rtd-single-cpu-sink",ret==0&&f.cpu_error==-ETIMEDOUT&&f.ss[0].xruns==1);
    cleanup(&f);
    setup(&f);f.ss[0].private_data=&rtd;f.prtd[0].exposed=false;rtd.num_cpus=2;
#if CANDIDATE
    f.prtd[0].error_sink=NULL;f.prtd[0].error_sink_arg=NULL;
#endif
    ret=dmaengine_pcm_open(&component,&f.ss[0]);publish(&f,-EIO);result_callback(&f.ss[0],&error);
    observe("generic-multi-cpu-no-binding",ret==0&&f.cpu_error==0);
    cleanup(&f);
    setup(&f);f.ss[0].private_data=&rtd;f.prtd[0].exposed=false;rtd.num_cpus=1;dai_ops.pcm_async_fault=NULL;
#if CANDIDATE
    f.prtd[0].error_sink=NULL;f.prtd[0].error_sink_arg=NULL;
#endif
    ret=dmaengine_pcm_open(&component,&f.ss[0]);publish(&f,-EIO);result_callback(&f.ss[0],&error);
    observe("generic-null-hook-no-binding",ret==0&&f.cpu_error==0);
    cleanup(&f);
    setup(&f);f.ss[0].private_data=&rtd;f.prtd[0].exposed=false;f.prtd[0].checked=false;dai_ops.pcm_async_fault=dai_fault;int closes=close_leaf_calls;
#if CANDIDATE
    f.prtd[0].error_sink=NULL;f.prtd[0].error_sink_arg=NULL;
#endif
    ret=dmaengine_pcm_open(&component,&f.ss[0]);
    observe("hook-on-unchecked-provider-rejects",ret==-EOPNOTSUPP&&close_leaf_calls==closes+1);
    cleanup(&f);
    setup(&f); f.controller.pm_failed=true; publish(&f,-EREMOTEIO); dispatch(&f);
    observe("real-dotask-pm-error-still-fanout",f.ss[0].xruns==1&&f.ss[1].xruns==1&&!atomic_read(&f.controller.producers));
    cleanup(&f);
#if CANDIDATE
    setup(&f);publish(&f,-ETIMEDOUT);atomic_store(&pause_sink,true);atomic_store(&sink_waiting,false);atomic_store(&allow_sink,false);
    pthread_t requeued_notifier;pthread_create(&requeued_notifier,NULL,notify_thread,&f);
    while(!atomic_load(&sink_waiting))usleep(1000);
    unsigned long queue_flags;spin_lock_irqsave(&f.controller.lock,queue_flags);f.controller.fault_tasklet_queued=true;tasklet_schedule(&f.controller.tasks);spin_unlock_irqrestore(&f.controller.lock,queue_flags);
    atomic_store(&allow_sink,true);pthread_join(requeued_notifier,NULL);atomic_store(&pause_sink,false);
    observe("real-dotask-preserves-new-queued-work",f.controller.fault_tasklet_queued&&f.controller.tasks.queued);
    int notifications=f.cpu_stop;dispatch(&f);
    observe("same-epoch-not-notified-twice",f.cpu_stop==notifications&&!f.controller.fault_tasklet_queued);
    cleanup(&f);
#else
    observe("real-dotask-preserves-new-queued-work",false);
    observe("same-epoch-not-notified-twice",false);
#endif
    setup(&f);list_del_init(&f.desc[0].node);f.ss[0].state=1;inject_terminate_errno=-EREMOTEIO;
    ret=snd_dmaengine_pcm_quiesce(&f.ss[0]);
    observe("prepare-new-fault-during-sync-notifies-cpu",ret==-EREMOTEIO&&f.cpu_error==-EREMOTEIO);
    observe("sync-new-fault-still-quarantines",f.prtd[0].quarantine->consumed&&!f.prtd[0].exposed);
    cleanup(&f);
    printf("RESULT observations=%d failed=%d\n",observations,failures);
    return failures?1:0;
}
