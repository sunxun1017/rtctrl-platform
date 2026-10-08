static int failures;
static struct i2c_adapter adapter;
static struct device_node node;
static struct i2c_device_id devid = {"gs_mxc6655xa", ACCEL_ID_MXC6655XA};
static int report_stub(struct i2c_client *client) { return 0; }
static int init_stub(struct i2c_client *client) { return init_fault; }
static struct sensor_operate ops;
static struct sensor_platform_data pdata;
static struct sensor_private_data private_data;
static struct i2c_client client;

static void reset(void)
{
    memset(registers, 0, sizeof(registers));
    memset(sensor_ops, 0, sizeof(sensor_ops));
    memset(g_sensor, 0, sizeof(g_sensor));
    memset(&private_data, 0, sizeof(private_data));
    memset(&pdata, 0, sizeof(pdata));
    memset(&ops, 0, sizeof(ops));
    client = (struct i2c_client){.adapter = &adapter, .addr = 0x15, .dev.of_node = &node};
    transfer_result = 99;
    fault_call = calls = writes = init_fault = input_fault = misc_fault = 0;
    irq_calls = input_calls = enable_calls = 0;
    work_inits = work_schedules = 0;
    registers[0x0f] = 5;
    ops = (struct sensor_operate){.name = "gs_mxc6655xa", .type = SENSOR_TYPE_ACCEL,
        .id_i2c = ACCEL_ID_MXC6655XA, .id_reg = 0x0f, .id_data = 5, .ctrl_reg = 0x0d,
        .active = sensor_active, .init = sensor_init, .report = report_stub};
    private_data = (struct sensor_private_data){.client = &client, .pdata = &pdata,
        .ops = &ops, .i2c_id = &devid, .type = SENSOR_TYPE_ACCEL};
    client.data = &private_data;
    sensor_ops[ACCEL_ID_MXC6655XA] = &ops;
}

static void check(const char *name, int got, int expected)
{
    printf("%s got=%d expected=%d %s\n", name, got, expected, got == expected ? "PASS" : "FAIL");
    failures += got != expected;
}

int main(void)
{
    int result, id;
    char byte = 0x0f;
    reset();
    check("correct-id", sensor_get_id(&client, &id), 0);
    check("id-value", id, 5);
    reset();
    registers[0x0f] = 4;
    check("wrong-id", sensor_get_id(&client, &id), -ENODEV);
    reset();
    transfer_result = -EREMOTEIO;
    check("negative-read", sensor_read_reg(&client, 0x0f), -EREMOTEIO);
    reset();
    transfer_result = 1;
    check("short-two-message-transfer", sensor_rx_data(&client, &byte, 1), -EIO);
    reset();
    transfer_result = 0;
    check("zero-read-transfer", sensor_read_reg(&client, 0x0f), -EIO);
    reset();
    registers[0x0d] = 0xff;
    check("unsigned-register-value", sensor_read_reg(&client, 0x0d), 255);
    reset();
    transfer_result = -EREMOTEIO;
    fault_call = 1;
    check("active-read-error", sensor_active(&client, 0, 0), -EREMOTEIO);
    check("active-read-error-no-write", writes, 0);
    check("active-read-error-no-write-attempt", calls, 1);
    reset();
    transfer_result = 0;
    fault_call = 2;
    check("active-short-write", sensor_active(&client, 0, 0), -EIO);
    reset();
    transfer_result = -EREMOTEIO;
    fault_call = 2;
    ops.ctrl_data = 0x40;
    check("active-negative-write", sensor_active(&client, 0, 0), -EREMOTEIO);
    check("active-negative-write-cache-unchanged", ops.ctrl_data, 0x40);
    reset();
    registers[0x0d] = 0x41;
    check("active-on", sensor_active(&client, 1, 0), 0);
    check("active-on-preserves-other-bits", registers[0x0d], 0x40);
    reset();
    transfer_result = 0;
    check("normal-short-read", sensor_rx_data_normal(&client, &byte, 1), -EIO);
    check("normal-short-write", sensor_tx_data_normal(&client, &byte, 1), -EIO);
    check("normal-short-read-reg", sensor_read_reg_normal(&client), -EIO);
    reset();
    transfer_result = -EREMOTEIO;
    check("normal-negative-read-reg", sensor_read_reg_normal(&client), -EREMOTEIO);
    reset();
    registers[0] = 0xff;
    check("normal-unsigned-register-value", sensor_read_reg_normal(&client), 255);
    reset();
    transfer_result = -EIO;
    fault_call = 4;
    check("init-mask-read-error", sensor_init(&client), -EIO);
    check("init-mask-read-error-no-mask-write", writes, 2);
    reset();
    check("default-init-off", sensor_init(&client), 0);
    check("default-status-off", private_data.status_cur, SENSOR_OFF);
    check("default-control-powerdown", registers[0x0d] & 1, 1);
    reset();
    transfer_result = -EREMOTEIO;
    fault_call = 3;
    check("init-control-write-error", sensor_init(&client), -EREMOTEIO);
    check("init-control-error-stays-off", registers[0x0d] & 1, 1);
    check("init-control-error-no-mask-access", calls, 3);
    reset();
    ops.init = init_stub;
    init_fault = -EFAULT;
    check("chip-init-propagates-init", sensor_chip_init(&client), -EFAULT);
    reset();
    registers[0x0f] = 0;
    check("chip-init-wrong-id", sensor_chip_init(&client), -ENODEV);
    reset();
    transfer_result = -EREMOTEIO;
    check("chip-init-i2c-error", sensor_chip_init(&client), -EREMOTEIO);
    reset();
    sensor_ops[ACCEL_ID_MXC6655XA] = NULL;
    check("register-default-off", sensor_register_device(&client, NULL, &devid, &ops), 0);
    check("probe-no-poll-schedule", ((struct sensor_private_data *)client.data)->stop_work, 1);
    check("probe-success-status-off", ((struct sensor_private_data *)client.data)->status_cur, SENSOR_OFF);
    check("probe-input-registered", input_calls, 1);
    check("probe-poll-work-initialized", work_inits, 1);
    check("probe-poll-work-not-scheduled", work_schedules, 0);
    check("probe-poll-no-irq-request", irq_calls, 0);
    reset();
    transfer_result = -EREMOTEIO;
    check("register-negative-i2c", sensor_register_device(&client, NULL, &devid, &ops), -EREMOTEIO);
    check("register-negative-i2c-no-input", input_calls, 0);
    check("register-negative-i2c-no-global", g_sensor[SENSOR_TYPE_ACCEL] == NULL, 1);
    reset();
    registers[0x0f] = 0;
    result = sensor_register_device(&client, NULL, &devid, &ops);
    check("register-propagates-wrong-id", result, -ENODEV);
    check("failed-probe-no-global-sensor", g_sensor[SENSOR_TYPE_ACCEL] == NULL, 1);
    check("failed-probe-no-input", input_calls, 0);
    check("failed-probe-clears-ops", sensor_ops[ACCEL_ID_MXC6655XA] == NULL, 1);
    check("failed-probe-clears-clientdata", client.data == NULL, 1);
    reset();
    ops.init = init_stub;
    init_fault = -EFAULT;
    check("register-propagates-init-error", sensor_register_device(&client, NULL, &devid, &ops), -EFAULT);
    check("init-error-no-global-sensor", g_sensor[SENSOR_TYPE_ACCEL] == NULL, 1);
    reset();
    input_fault = -ENOMEM;
    check("register-propagates-input-error", sensor_register_device(&client, NULL, &devid, &ops), -ENOMEM);
    check("input-error-no-global-sensor", g_sensor[SENSOR_TYPE_ACCEL] == NULL, 1);
    reset();
    misc_fault = -EBUSY;
    check("register-propagates-misc-error", sensor_register_device(&client, NULL, &devid, &ops), -EBUSY);
    check("misc-error-no-global-sensor", g_sensor[SENSOR_TYPE_ACCEL] == NULL, 1);
    check("misc-error-default-off", registers[0x0d] & 1, 1);
    printf("TOTAL_FAILURES=%d\n", failures);
    return failures ? 1 : 0;
}
