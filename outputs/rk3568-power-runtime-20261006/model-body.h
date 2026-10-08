static int regmap_field_read(struct regmap_field *r,unsigned int *out) {
    int field=r->field;
    if (read_error==field) return -EIO;
    int val;
    switch (field) {
    case PLUG_IN_STS:
        val=plug_sample;
        if(plug_event_during_read&&pdev.dev.data) {
            int event=plug_event_during_read; plug_event_during_read=0;
            if(event==1) rk809_plug_in_isr(21,pdev.dev.data);
            else rk809_plug_out_isr(22,pdev.dev.data);
        }
        break;
    case VCALIB0_H: val=0; break;
    case VCALIB0_L: val=100; break;
    case VCALIB1_H: val=property_invalid==10?0:1; break;
    case VCALIB1_L: val=property_invalid==10?100:144; break;
    case IOFFSET_H: val=0; break;
    case IOFFSET_L: val=42; break;
    default: val=0; break;
    }
    *out=val; return 0;
}
static int regmap_field_write(struct regmap_field *r,unsigned int val) { writes++; return 0; }
static void rk817_bat_init_info(struct rk817_battery_device *b) { b->monitor_ms=5000; b->fcc=3500; }
static void rk817_battery_debug_info(struct rk817_battery_device *b) {}
static void rk817_bat_update_info(struct rk817_battery_device *b) {
    updates++;
    engine_pause(1);
#ifdef CANDIDATE
    if (trigger_stop) { b->stopped=true; trigger_stop=0; }
#endif
}
#define rk817_bat_lowpwr_check(b) do {} while (0)
#define rk817_bat_display_smooth(b) do {} while (0)
#define rk817_bat_power_supply_changed(b) power_supply_changed((b)->bat)
#define rk817_bat_save_data(b) do {} while (0)
#define rk817_bat_output_info(b) do {} while (0)
#define rk817_bat_smooth_algo_prepare(b) do {} while (0)
static int rk817_bat_init_power_supply(struct rk817_battery_device *b) { if (fail_ps) return -EIO; b->bat=&bat_ps; bat_ps.live=1; bat_ps.data=b; live_ps++; register_order++; resources[resource_count++]=(struct resource){.kind=1,.key=1}; return 0; }
static int rk809_chg_init_power_supply(struct rk817_battery_device *b) { if (fail_chg_ps) return -EIO; b->chg_psy=&chg_ps; chg_ps.live=1; chg_ps.data=b; live_ps++; register_order++; resources[resource_count++]=(struct resource){.kind=1,.key=2}; return 0; }
static int get_charge_status(struct rk817_battery_device *b) { return 0; }
static int rk817_bat_get_avg_current(struct rk817_battery_device *b) { engine_pause(2); return -10; }
static int rk817_bat_get_capacity_uah(struct rk817_battery_device *b) { return 1000000; }
static int rk817_bat_get_rsoc(struct rk817_battery_device *b) { return 25; }
static int rk817_bat_get_battery_voltage(struct rk817_battery_device *b) { return 3900; }
static int rk817_bat_get_relax_voltage(struct rk817_battery_device *b) { return 3900; }
static int rk817_bat_sleep_dischrg(struct rk817_battery_device *b) { return 0; }
static unsigned long get_boot_sec(void) { return 123; }
static void rk817_bat_internal_calib(struct work_struct *w) {}
static void rk817_bat_resume_work(struct work_struct *work);
#define rk817_bat_adc_init(b) do { writes++; } while(0)
#define rk817_bat_gas_gaugle_enable(b) do { writes++; } while(0)
#define rk817_bat_gg_con_init(b) do { writes++; } while(0)
#define rk817_bat_set_relax_sample(b) do { writes++; } while(0)
#define rk817_bat_ocv_thre(b,v) do { writes++; } while(0)
#define rk817_bat_rsoc_init(b) do {} while(0)
#define rk817_bat_init_coulomb_cap(b,v) do { writes++; } while(0)
#define rk817_bat_init_dsoc_algorithm(b) do {} while(0)
#define rk817_bat_get_qmax(b) 3750
#define rk817_bat_get_sys_voltage(b) 3900
#define rk817_bat_get_ocv_voltage(b) 3900

static void reset(void) {
    for (int i=0;i<16;i++) { free(allocated[i]); allocated[i]=NULL; }
    memset(&pdev,0,sizeof(pdev)); memset(&client,0,sizeof(client));
    memset(&wq,0,sizeof(wq)); memset(&bat_ps,0,sizeof(bat_ps)); memset(&chg_ps,0,sizeof(chg_ps));
    pmic.i2c=&client; pmic.variant=RK809_ID; pmic.regmap=&regmap; pdev.dev.parent=&client.dev; client.dev.data=&pmic;
    bad=fail_ps=fail_chg_ps=fail_virq=fail_irq=fail_action=0;
    queues=updates=writes=cancels=irq_count=destroyed=wake_count=live_ps=0;
    property_invalid=read_error=trigger_stop=field_failure=0;
    register_order=first_queue_order=allocations=last_owner_pdev=0;
    rtc_fail=rtc_refs=irq_callbacks=resource_count=irq_mask=debug_on=plug_sample=plug_event_during_read=ps_notifications=0;
    memset(resources,0,sizeof(resources));
    fail_alloc=-1; ocv_count=21; cleanup_action=NULL; cleanup_data=NULL;
}
static void release_devres(void) {
    struct resource todo[32];
    int count=resource_count;
    memcpy(todo,resources,sizeof(todo));
    memset(resources,0,sizeof(resources)); resource_count=0;
    /* Real release_all moves devres nodes to todo before callbacks. */
    for(int i=count-1;i>=0;i--) {
        struct resource r=todo[i];
        if(r.kind==3) r.action(r.data);
        if(r.kind==2) irq_count--;
        if(r.kind==1) {
            struct rk817_battery_device *b=pdev.dev.data;
            if(b&&(b->bat_delay_work.work.pending||b->resume_work.pending||b->calib_delay_work.work.pending||b->caltimer.pending||irq_count)) bad++;
            if(r.key==1) bat_ps.live=0; else chg_ps.live=0;
            live_ps--;
        }
    }
    resource_count=0;
}
static int failures, checks;
#define CHECK(test, label) do { checks++; if (!(test)) { printf("FAIL %s\n",label); failures++; } else printf("PASS %s\n",label); } while (0)
