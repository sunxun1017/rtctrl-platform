static void finish(void) { release_devres(); }
static void run_success(void) {
    int rc=rk817_battery_probe(&pdev);
    instance=pdev.dev.data;
    CHECK(rc==0,"valid probe succeeds");
    CHECK(last_owner_pdev,"battery allocation owned by platform device");
    CHECK(bad==0,"async initialization before publication");
    CHECK(first_queue_order>3,"first monitor queue follows PS and both IRQ");
    CHECK(instance->pdev==&pdev,"pdev assigned before IRQ diagnostics");
    CHECK(instance->bat_delay_work.work.pending==1,"monitor published on success");
    CHECK(instance->caltimer.pending==1,"timer published on success");
    CHECK(irq_count==2,"both IRQ registered on success");
    CHECK(irq_callbacks==2,"threaded IRQ injected at each installation point");
    CHECK(wake_count==1,"wake lock initialized once");
    rk817_battery_work(&instance->bat_delay_work.work);
    CHECK(queues==2,"active monitor requeues");
    rk809_plug_in_isr(21,instance);
    rk809_plug_out_isr(22,instance);
    CHECK(bad==0,"active IRQ sees valid PS");
    rk817_bat_pm_suspend(&pdev.dev);
    CHECK(instance->bat_delay_work.work.pending==0,"suspend drains monitor");
    CHECK(instance->caltimer.pending==0,"suspend drains calibration timer");
    CHECK(instance->calib_delay_work.work.pending==0,"suspend drains calibration work");
    CHECK(instance->resume_work.pending==0,"suspend drains prior resume work");
    int saved_queues=queues,saved_updates=updates;
    rk817_battery_work(&instance->bat_delay_work.work);
    rk817_bat_caltimer_isr(&instance->caltimer);
    CHECK(queues==saved_queues&&updates==saved_updates,"late suspend callbacks cannot requeue or update");
    rk817_bat_pm_resume(&pdev.dev);
    CHECK(instance->resume_work.pending==1,"resume publishes resume work");
    CHECK(instance->caltimer.pending==1,"resume restores calibration timer");
    rk817_bat_resume_work(&instance->resume_work);
    CHECK(instance->bat_delay_work.work.pending==1,"resume work restores monitor");
    rk817_battery_shutdown(&pdev);
    CHECK(instance->bat_delay_work.work.pending==0&&!instance->caltimer.pending,"shutdown drains timer and monitor");
    CHECK(instance->resume_work.pending==0&&!instance->calib_delay_work.work.pending,"shutdown drains resume and calib");
    CHECK(irq_count==0,"shutdown synchronously releases IRQ");
    CHECK(destroyed==1&&!wq.live&&wake_count==0,"shutdown releases WQ and wake lock");
    saved_queues=queues; saved_updates=updates;
    rk817_bat_pm_resume(&pdev.dev);
    rk817_battery_work(&instance->bat_delay_work.work);
    rk817_bat_caltimer_isr(&instance->caltimer);
    rk817_bat_resume_work(&instance->resume_work);
    CHECK(queues==saved_queues&&updates==saved_updates,"permanent stop cannot be resumed");
#ifdef CANDIDATE
    rk817_battery_remove(&pdev);
    CHECK(destroyed==1&&wake_count==0,"remove after shutdown is idempotent");
#else
    CHECK(0,"remove after shutdown is idempotent");
#endif
    finish();
    CHECK(destroyed==1&&wake_count==0&&bad==0,"devres stop after remove remains idempotent");
}
static void probe_failures(void) {
    for (int stage=0;stage<10;stage++) {
        reset();
        switch(stage) {
        case 0: fail_alloc=0; break;
        case 1: field_failure=1; break;
        case 2: fail_alloc=99; break;
        case 3: fail_ps=1; break;
        case 4: property_invalid=11; fail_chg_ps=1; break;
        case 5: fail_virq=1; break;
        case 6: fail_virq=2; break;
        case 7: fail_irq=1; break;
        case 8: fail_irq=2; break;
        case 9: fail_action=1; break;
        }
        int rc=rk817_battery_probe(&pdev);
        instance=pdev.dev.data;
        char label[96];
        snprintf(label,sizeof(label),"probe failure %d returns errno",stage);
        CHECK(rc<0,label);
        snprintf(label,sizeof(label),"probe failure %d no early publication",stage);
        CHECK(queues==0&&(!instance||!instance->caltimer.pending),label);
        finish();
        snprintf(label,sizeof(label),"probe failure %d resources drained",stage);
        CHECK(!wq.live&&wake_count==0&&irq_count==0&&bad==0,label);
    }
}
static void input_failures(void) {
    int kinds[]={0,1,2,3,4,5,6,7,8,9};
    for (unsigned i=0;i<ARRAY_SIZE(kinds);i++) {
        reset();
        property_invalid=kinds[i];
        if (i==0) ocv_count=1;
        struct rk817_battery_device b={.dev=&pdev.dev,.chip_id=RK809_ID};
        int rc=rk817_bat_parse_dt(&b);
        char label[80]; snprintf(label,sizeof(label),"invalid DT class %u rejected",i);
        CHECK(rc<0,label);
    }
    reset(); ocv_count=256;
    struct rk817_battery_device b={.dev=&pdev.dev,.chip_id=RK809_ID};
    CHECK(rk817_bat_parse_dt(&b)<0,"u8 interpolation index cannot wrap at 256 entries");
    reset();
    b=(struct rk817_battery_device){.dev=&pdev.dev,.chip_id=RK809_ID};
    CHECK(rk817_bat_parse_dt(&b)==0,"original board parameter shape accepted");
    for(int i=0;i<18;i++) { register_fields[i].field=i; b.rmap_fields[i]=&register_fields[i]; }
    for(int field=VCALIB0_H;field<=VCALIB1_L;field++) {
        read_error=field; b.voltage_k=123; b.voltage_b=456;
#ifdef CANDIDATE
        b.io_error=0;
        int rc=rk817_bat_init_voltage_kb(&b);
        CHECK(rc==-EIO&&b.voltage_k==123&&b.voltage_b==456,"calibration read errno propagated without publication");
#else
        rk817_bat_init_voltage_kb(&b);
        CHECK(b.voltage_k==123&&b.voltage_b==456,"calibration read errno propagated without publication");
#endif
    }
    read_error=0;
    b.voltage_k=123; b.voltage_b=456;
#ifdef CANDIDATE
    b.io_error=0;
    CHECK(rk817_bat_init_voltage_kb(&b)==0,"valid original calibration arithmetic preserved");
    CHECK(b.voltage_k==1500&&b.voltage_b==450,"original RK809 calibration result preserved");
#else
    rk817_bat_init_voltage_kb(&b);
    CHECK(b.voltage_k==1500&&b.voltage_b==450,"original RK809 calibration result preserved");
#endif
}
static void io_and_rtc(void) {
    reset();
    for(int mode=0;mode<4;mode++) {
        rtc_fail=mode;
        if(mode==1) {
#ifdef CANDIDATE
            CHECK(rk817_get_rtc_sec()==0,"absent RTC handled");
#endif
            continue;
        }
        time64_t sec=rk817_get_rtc_sec();
        CHECK(sec==(mode==0?123:0),"RTC valid and error result");
        CHECK(rtc_refs==0,"RTC reference returned on all paths");
        rtc_refs=0;
    }
#ifdef CANDIDATE
    struct rk817_battery_device b={0};
    for(int i=0;i<18;i++) { register_fields[i].field=i; b.rmap_fields[i]=&register_fields[i]; }
    read_error=VCALIB0_H;
    CHECK(rk817_bat_field_read(&b,VCALIB0_H)==0&&b.io_error==-EIO,"negative read latches errno before byte composition");
    int before=writes;
    CHECK(rk817_bat_field_write(&b,CAL_OFFSET_L,42)==-EIO&&writes==before,"latched read error blocks later hardware writes");
    b.io_error=0;
    CHECK(rk817_bat_init_fg(&b)==-EIO&&writes==before,"real init_fg rejects calibration read before first write");
    CHECK(!b.caltimer.pending,"real init_fg has no timer publication");
    union power_supply_propval value={0};
    struct power_supply chg={.data=&b};
    CHECK(rk809_chg_get_property(&chg,POWER_SUPPLY_PROP_STATUS,&value)==-EIO,"charger-view property propagates sticky errno");
    reset();
    CHECK(rk817_battery_probe(&pdev)==0,"devres-only fallback probe");
    finish();
    CHECK(irq_count==0&&irq_mask==0&&bad==0&&destroyed==1&&wake_count==0,"detached devres fallback releases owned IRQ exactly once");
    for(int invalid=12;invalid<=14;invalid++) {
        reset(); property_invalid=invalid;
        int rc=rk817_battery_probe(&pdev);
        CHECK(rc<0,"invalid OCV representation or divider overflow rejected");
        finish();
        CHECK(!wq.live&&!irq_count&&!wake_count,"invalid representation leaves no async resources");
    }
    for(int field=CHIP_NAME_H;field<=CHIP_NAME_L;field++) {
        reset(); debug_on=1; read_error=field;
        int rc=rk817_battery_probe(&pdev);
        instance=pdev.dev.data;
        CHECK(rc==-EIO,"enabled debug-register read failure rejects probe");
        CHECK(queues==0&&instance&&!instance->caltimer.pending,"debug-register failure precedes publication");
        finish();
        CHECK(!wq.live&&!irq_count&&!wake_count&&bad==0,"debug-register failure synchronously drains resources");
    }
#endif
}
static void running_requeue_cut(void) {
#ifdef CANDIDATE
    reset();
    CHECK(rk817_battery_probe(&pdev)==0,"requeue-cut probe");
    instance=pdev.dev.data;
    trigger_stop=1;
    int before=queues;
    rk817_battery_work(&instance->bat_delay_work.work);
    CHECK(queues==before,"stop observed after work begins prevents final requeue");
    /* Gate was set by hook; clear only to allow real stop to reclaim resources. */
    instance->stopped=false;
    rk817_battery_remove(&pdev);
    CHECK(!wq.live&&wake_count==0&&irq_count==0,"remove reclaims successful-probe resources");
    finish();
#endif
}
static void paused_plug_events(void) {
#ifdef CANDIDATE
    reset(); CHECK(rk817_battery_probe(&pdev)==0,"paused plug probe");
    instance=pdev.dev.data;
    rk817_bat_pm_suspend(&pdev.dev);
    int notices=ps_notifications;
    rk809_plug_in_isr(21,instance);
    CHECK(instance->plugin_trigger==1,"paused plug event updates latest cache");
    CHECK(ps_notifications==notices,"paused event defers notification");
    plug_sample=1;
    rk817_bat_pm_resume(&pdev.dev);
    CHECK(instance->plugin_trigger==1,"resume retains latest plug state");
    CHECK(ps_notifications>notices,"resume publishes deferred notification");
    rk817_bat_pm_suspend(&pdev.dev);
    notices=ps_notifications;
    rk809_plug_out_isr(22,instance);
    CHECK(instance->plugin_trigger==0,"paused unplug event updates latest cache");
    CHECK(ps_notifications==notices,"paused unplug defers notification");
    plug_sample=0; rk817_bat_pm_resume(&pdev.dev);
    CHECK(instance->plugin_trigger==0,"resume refresh observes latest unplug state");
    rk817_battery_remove(&pdev); finish();
    reset(); plug_sample=0; plug_event_during_read=1;
    CHECK(rk817_battery_probe(&pdev)==0,"probe concurrent plug event");
    instance=pdev.dev.data;
    CHECK(instance->plugin_trigger==1,"probe read cannot overwrite newer IRQ event");
    rk817_bat_pm_suspend(&pdev.dev);
    plug_sample=1; plug_event_during_read=2;
    rk817_bat_pm_resume(&pdev.dev);
    CHECK(instance->plugin_trigger==0,"resume read cannot overwrite newer IRQ event");
    rk817_battery_remove(&pdev); finish();
    CHECK(bad==0&&!irq_count&&!wake_count,"plug-event cleanup remains safe");
#endif
}
int main(void) {
    reset(); run_success();
    probe_failures(); input_failures(); io_and_rtc(); running_requeue_cut(); paused_plug_events();
    printf("RESULT checks=%d failed=%d\n",checks,failures);
    reset(); return failures?1:0;
}
