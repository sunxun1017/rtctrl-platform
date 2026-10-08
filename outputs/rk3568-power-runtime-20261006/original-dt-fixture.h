/* Original board DT cells; not a new battery calibration. */
static const u32 original_ocv[] = {7000,7250,7370,7384,7436,7470,7496,7520,7548,7576,7604,7632,7668,7706,7754,7816,7892,7950,8036,8142,8212};
static int original_dt_u32(const char *name,u32 *value) {
    if (!strcmp(name,"design_capacity")) { *value=3500; return 0; }
    if (!strcmp(name,"design_qmax")) { *value=3750; return 0; }
    if (!strcmp(name,"bat_res")) { *value=100; return 0; }
    if (!strcmp(name,"sleep_enter_current")) { *value=300; return 0; }
    if (!strcmp(name,"sleep_exit_current")) { *value=300; return 0; }
    if (!strcmp(name,"sleep_filter_current")) { *value=100; return 0; }
    if (!strcmp(name,"power_off_thresd")) { *value=7000; return 0; }
    if (!strcmp(name,"zero_algorithm_vol")) { *value=7700; return 0; }
    if (!strcmp(name,"max_soc_offset")) { *value=60; return 0; }
    if (!strcmp(name,"monitor_sec")) { *value=5; return 0; }
    if (!strcmp(name,"sample_res")) { *value=10; return 0; }
    if (!strcmp(name,"virtual_power")) { *value=0; return 0; }
    if (!strcmp(name,"bat_res_up")) { *value=140; return 0; }
    if (!strcmp(name,"bat_res_down")) { *value=20; return 0; }
    return -EINVAL;
}
