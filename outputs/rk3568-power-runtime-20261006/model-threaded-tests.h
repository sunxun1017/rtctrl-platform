/* Actual production callbacks run on pthreads; fake cancel joins them. */
static void finish(void) { release_devres(); }
static void *run_work_thread(void *data) {
    struct work_struct *w=data;
    w->pending=0;
    w->function(w);
    return NULL;
}
static void *run_stop_thread(void *data) {
    atomic_store(&engine_stop_started,1);
    if((intptr_t)data==1) rk817_bat_pm_suspend(&pdev.dev);
    else if((intptr_t)data==2) rk817_battery_shutdown(&pdev);
    else rk817_battery_remove(&pdev);
    atomic_store(&engine_stop_done,1);
    return NULL;
}
static void *run_timer_thread(void *data) { instance->caltimer.function(&instance->caltimer); return NULL; }
static void *run_irq_thread(void *data) { engine_irq_functions[0](21,instance); return NULL; }
static void *run_second_stop(void *data) { rk817_battery_shutdown(&pdev); return NULL; }
static void run_cut(int work_kind,int stop_kind) {
    reset();
    engine_block_stage=engine_entered=engine_release=0;
    atomic_store(&engine_join_entered,0); atomic_store(&engine_stop_done,0); atomic_store(&engine_stop_started,0);
    CHECK(rk817_battery_probe(&pdev)==0,"threaded production probe succeeds");
    instance=pdev.dev.data;
    struct work_struct *work;
    if(work_kind==1) work=&instance->bat_delay_work.work;
    else {
        rk817_bat_pm_suspend(&pdev.dev);
        rk817_bat_pm_resume(&pdev.dev);
        work=&instance->resume_work;
    }
    engine_block_stage=work_kind;
    work->thread_started=1;
    pthread_create(&work->thread,NULL,run_work_thread,work);
    pthread_mutex_lock(&engine_lock);
    while(!engine_entered) pthread_cond_wait(&engine_cv,&engine_lock);
    pthread_mutex_unlock(&engine_lock);
    pthread_t stopper,second;
    pthread_create(&stopper,NULL,run_stop_thread,(void *)(intptr_t)stop_kind);
    while(!atomic_load(&engine_join_entered)) sched_yield();
    CHECK(!atomic_load(&engine_stop_done),"stop or suspend waits for running callback");
    CHECK(wq.live&&wake_count==1,"WQ and wake owner live until running callback exits");
    CHECK(stop_kind==1 ? instance->suspended : instance->stopped,"publication gate closed before callback join");
    if(stop_kind!=1) pthread_create(&second,NULL,run_second_stop,NULL);
    int queued=queues;
    pthread_mutex_lock(&engine_lock);
    engine_release=1; pthread_cond_broadcast(&engine_cv);
    pthread_mutex_unlock(&engine_lock);
    pthread_join(stopper,NULL);
    if(stop_kind!=1) pthread_join(second,NULL);
    CHECK(queues==queued,"running callback cannot requeue across stop gate");
    CHECK(!instance->bat_delay_work.work.pending&&!instance->resume_work.pending,"both work items drained after running callback");
    if(stop_kind==1) {
        CHECK(wq.live&&wake_count==1&&irq_count==2,"suspend retains owners without destroying them");
        rk817_bat_pm_resume(&pdev.dev);
        CHECK(instance->resume_work.pending==1,"successful resume remains possible after pause");
        rk817_battery_remove(&pdev);
    } else {
        CHECK(destroyed==1&&wake_count==0&&irq_count==0,"concurrent remove and shutdown reclaim exactly once");
        rk817_bat_pm_resume(&pdev.dev);
        CHECK(!instance->resume_work.pending,"PM resume cannot revive permanent stop");
    }
    finish();
    CHECK(!wq.live&&!irq_count&&destroyed==1&&bad==0,"final devres fallback is idempotent after running drain");
    engine_block_stage=0;
}
static void extra_cut(int kind,int stop_kind) {
    reset(); engine_block_stage=engine_entered=engine_release=0;
    atomic_store(&engine_join_entered,0); atomic_store(&engine_stop_done,0); atomic_store(&engine_stop_started,0);
    CHECK(rk817_battery_probe(&pdev)==0,"timer or IRQ threaded probe succeeds");
    instance=pdev.dev.data; engine_block_stage=kind;
    if(kind==3) {
        instance->caltimer.thread_started=1;
        pthread_create(&instance->caltimer.thread,NULL,run_timer_thread,NULL);
    } else {
        engine_irq_running[0]=1;
        pthread_create(&engine_irq_threads[0],NULL,run_irq_thread,NULL);
    }
    pthread_mutex_lock(&engine_lock);
    while(!engine_entered) pthread_cond_wait(&engine_cv,&engine_lock);
    pthread_mutex_unlock(&engine_lock);
    pthread_t stopper;
    pthread_create(&stopper,NULL,run_stop_thread,(void *)(intptr_t)stop_kind);
    if(kind==4) while(!atomic_load(&engine_join_entered)&&!atomic_load(&engine_stop_done)) sched_yield();
    else while(!atomic_load(&engine_stop_started)) sched_yield();
    CHECK(!atomic_load(&engine_stop_done),"stop waits for running timer or IRQ publication");
    CHECK(wq.live&&wake_count==1&&bat_ps.live,"owners remain live during timer or IRQ callback");
    pthread_mutex_lock(&engine_lock); engine_release=1; pthread_cond_broadcast(&engine_cv); pthread_mutex_unlock(&engine_lock);
    pthread_join(stopper,NULL);
    if(kind==4&&stop_kind==1&&engine_irq_running[0]) {
        pthread_join(engine_irq_threads[0],NULL); engine_irq_running[0]=0;
    }
    CHECK(!instance->caltimer.pending&&!instance->calib_delay_work.work.pending,"timer and calibration publication drained");
    if(stop_kind==1) {
        CHECK(wq.live&&wake_count==1&&irq_count==2,"timer or IRQ suspend retains lifetime owners");
        rk817_battery_remove(&pdev);
    } else CHECK(destroyed==1&&!irq_count&&!wake_count,"timer or IRQ stop frees each owner once");
    finish();
    CHECK(!wq.live&&!irq_count&&destroyed==1&&bad==0,"timer or IRQ final devres remains safe");
    engine_block_stage=0;
}
int main(void) {
    for(int work=1;work<=2;work++) for(int stop=0;stop<3;stop++) run_cut(work,stop);
    for(int kind=3;kind<=4;kind++) for(int stop=0;stop<3;stop++) extra_cut(kind,stop);
    printf("RESULT checks=%d failed=%d\n",checks,failures);
    reset(); return failures?1:0;
}
