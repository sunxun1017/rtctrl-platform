/* SPDX-License-Identifier: MIT */
/* Every case catches a lost errno, unwanted I/O, wrong argument or unsafe state transition. */
enum operation {
    REG_ENABLE, REG_DISABLE, REG_STATUS, ENABLE_ON, ENABLE_OFF, RESET_ON, RESET_OFF,
    HPD_GET, HPD_READ, GENERIC, DCS, COMPRESSION, PPS, ALLOCATION, SLEEP, SPI,
    OP_COUNT
};
struct event { enum operation op; size_t arg; size_t extra; u8 bytes[128]; };
struct injection { enum operation op; int occurrence; int value; };
static struct event events[1024];
static int event_count, occurrences[OP_COUNT];
static struct injection injections[12];
static int injection_count, supply_refs, hpd_value, hpd_lookup_error;
static bool alloc_fail;
static struct device device;
static struct regulator supply;
static struct gpio_desc enable_gpio = {1}, reset_gpio = {2}, hpd_gpio = {3};
static struct mipi_dsi_device dsi;
static struct dw_mipi_dsi host;
static const struct mipi_dsi_host_ops host_ops = {.transfer = dw_mipi_dsi_host_transfer};
static struct mipi_dsi_msg active_message;
static struct mipi_dsi_packet last_packet;
static struct panel_desc desc;
static struct panel_simple panel;
static u8 payloads[3][4] = {{0x80, 0x12}, {0x11}, {0xa0, 0x21, 0x32, 0x43}};
static struct panel_cmd_desc cmds[3];
static struct panel_cmd_seq seq;
static struct drm_dsc_picture_parameter_set allocated_pps;
static char test_name[128], failures[256][512];
static int tests, failed, failure_count;
static bool this_failed;
static int marker_count, marker_transfer_count;
static bool marker_prepared;

static __attribute__((unused)) void test_dev_info(struct device *dev)
{
    marker_count++;
    marker_transfer_count = occurrences[GENERIC] + occurrences[DCS] + occurrences[SPI];
    marker_prepared = panel.prepared;
}

static int record(enum operation op, size_t arg, size_t extra, const void *data, int success)
{
    struct event *event = &events[event_count++];
    if (event_count > 1024) abort();
    event->op = op;
    event->arg = arg;
    event->extra = extra;
    if (data && arg <= sizeof(event->bytes)) memcpy(event->bytes, data, arg);
    occurrences[op]++;
    for (int i = 0; i < injection_count; i++) {
        if (injections[i].op == op && injections[i].occurrence == occurrences[op])
            return injections[i].value;
    }
    return success;
}
static void inject(enum operation op, int occurrence, int value)
{
    injections[injection_count++] = (struct injection){op, occurrence, value};
}
static int regulator_enable(struct regulator *r)
{
    int result = record(REG_ENABLE, 0, 0, NULL, 0);
    if (!result) supply_refs++;
    return result;
}
static int regulator_disable(struct regulator *r)
{
    int result = record(REG_DISABLE, 0, 0, NULL, 0);
    if (!result) supply_refs--;
    return result;
}
static int regulator_is_enabled(struct regulator *r)
{
    return record(REG_STATUS, 0, 0, NULL, supply_refs > 0);
}
static int gpiod_direction_output(struct gpio_desc *g, int value)
{
    /* The locked gpiolib optional-NULL API succeeds without touching hardware. */
    if (!g) return 0;
    enum operation op = g->id == 1 ? (value ? ENABLE_ON : ENABLE_OFF) :
                                         (value ? RESET_ON : RESET_OFF);
    return record(op, value, 0, NULL, 0);
}
static int gpiod_get_value_cansleep(struct gpio_desc *g)
{
    return record(HPD_READ, 0, 0, NULL, hpd_value);
}
static struct gpio_desc *devm_gpiod_get_optional(struct device *dev, const char *name, int flags)
{
    record(HPD_GET, flags, strcmp(name, "hpd"), NULL, 0);
    return hpd_lookup_error ? ERR_PTR(hpd_lookup_error) : &hpd_gpio;
}
static int test_poll(int value, bool asserted)
{
    return asserted ? 0 : -ETIMEDOUT;
}
static void usleep_range(unsigned long min, unsigned long max)
{
    record(SLEEP, min, max, NULL, 0);
}
static void *devm_kzalloc(struct device *dev, size_t bytes, int flags)
{
    record(ALLOCATION, bytes, flags, NULL, 0);
    return alloc_fail ? NULL : &allocated_pps;
}
static void dw_mipi_message_config(struct dw_mipi_dsi *d, const struct mipi_dsi_msg *msg)
{
    active_message = *msg;
}
static int dw_mipi_dsi_write(struct dw_mipi_dsi *d, const struct mipi_dsi_packet *packet)
{
    enum operation op;
    switch (active_message.type) {
    case 0x03: case 0x13: case 0x23: case 0x29:
        op = GENERIC;
        break;
    case 0x05: case 0x15: case 0x39:
        op = DCS;
        break;
    case 0x07:
        op = COMPRESSION;
        break;
    case 0x0a:
        op = PPS;
        break;
    default:
        abort();
    }
    last_packet = *packet;
    size_t arg = op == COMPRESSION ? ((const u8 *)active_message.tx_buf)[0] : active_message.tx_len;
    return record(op, arg, d == &host, op == COMPRESSION ? NULL : active_message.tx_buf, 0);
}
static int dw_mipi_dsi_read(struct dw_mipi_dsi *d, const struct mipi_dsi_msg *msg)
{
    abort(); /* This panel init/exit test never performs reads. */
}
static int spi_write(struct device *dev, const u8 *data, size_t len, u8 type)
{
    return record(SPI, len, type, data, 0);
}
static void reset_fixture(const char *name)
{
    if (tests && this_failed) failed++;
    tests++;
    snprintf(test_name, sizeof(test_name), "%s", name);
    this_failed = false;
    marker_count = marker_transfer_count = 0;
    marker_prepared = false;
    event_count = injection_count = supply_refs = hpd_lookup_error = 0;
    hpd_value = 1;
    alloc_fail = false;
    memset(events, 0, sizeof(events));
    memset(occurrences, 0, sizeof(occurrences));
    memset(&panel, 0, sizeof(panel));
    memset(&desc, 0, sizeof(desc));
    memset(&allocated_pps, 0, sizeof(allocated_pps));
    memset(&dsi, 0, sizeof(dsi));
    memset(&host, 0, sizeof(host));
    memset(&active_message, 0, sizeof(active_message));
    memset(&last_packet, 0, sizeof(last_packet));
    host.dev = &device;
    host.dsi_host.dev = &device;
    host.dsi_host.ops = &host_ops;
    dsi.host = &host.dsi_host;
    panel.base.dev = &device;
    panel.dsi = &dsi;
    panel.supply = &supply;
    panel.enable_gpio = &enable_gpio;
    panel.reset_gpio = &reset_gpio;
    panel.desc = &desc;
    desc.delay.prepare = 11;
    desc.delay.reset = 13;
    desc.delay.init = 17;
    desc.delay.enable = 19;
    desc.delay.disable = 23;
    desc.delay.unprepare = 29;
    desc.delay.hpd_absent_delay = 7;
    desc.spi_write = spi_write;
    for (int i = 0; i < 3; i++) {
        cmds[i].header = (struct panel_cmd_header){i == 1 ? 0x05 : 0x29, i + 3, i == 1 ? 1 : i == 0 ? 2 : 4};
        cmds[i].payload = payloads[i];
    }
    seq = (struct panel_cmd_seq){cmds, 3};
}
static void check(bool condition, const char *reason)
{
    if (!condition) {
        this_failed = true;
        if (failure_count < 256)
            snprintf(failures[failure_count++], 512, "%.127s: %.380s", test_name, reason);
    }
}
#define CHECK(c) check(!!(c), #c)
static void check_order(const enum operation *want, size_t count)
{
    CHECK(event_count == (int)count);
    for (size_t i = 0; i < count && i < (size_t)event_count; i++) CHECK(events[i].op == want[i]);
}
#define ORDER(...) do { const enum operation want[] = {__VA_ARGS__}; check_order(want, sizeof(want)/sizeof(want[0])); } while (0)
static void reject_after_fault(void)
{
    int before = event_count;
    int refs = supply_refs;
    CHECK(panel_simple_prepare(&panel.base) == -EIO);
    CHECK(panel_simple_enable(&panel.base) == -EIO);
    CHECK(panel_simple_unprepare(&panel.base) == -EIO);
    CHECK(panel_simple_loader_protect(&panel.base) == -EIO);
    CHECK(event_count == before);
    CHECK(supply_refs == refs);
    CHECK(!panel.prepared && !panel.enabled);
}
static void test_transfers(void)
{
    reset_fixture("null command sequence rejected");
    CHECK(panel_simple_xfer_dsi_cmd_seq(&panel, NULL) == -EINVAL);
    CHECK(event_count == 0);
    reset_fixture("unknown packet rejected without transfer");
    cmds[0].header.data_type = 0xff;
    CHECK(panel_simple_xfer_dsi_cmd_seq(&panel, &seq) == -EINVAL);
    CHECK(event_count == 0);
    const u8 types[] = {0x03, 0x13, 0x23, 0x29, 0x05, 0x15, 0x39};
    const u8 lengths[] = {0, 1, 2, 4, 1, 2, 4};
    /* Literal returns independently checked against create_packet + dw_host_transfer. */
    const int packet_bytes[] = {4, 4, 4, 8, 4, 4, 8};
    for (int i = 0; i < 7; i++) {
        char name[80];
        snprintf(name, sizeof(name), "real DSI API and DW host 0x%02x return packet size", types[i]);
        reset_fixture(name);
        CHECK((i < 4 ? mipi_dsi_generic_write(&dsi, payloads[0], lengths[i]) :
                       mipi_dsi_dcs_write_buffer(&dsi, payloads[0], lengths[i])) == packet_bytes[i]);
        CHECK(last_packet.size == (size_t)packet_bytes[i]);
        CHECK(last_packet.header[0] == types[i]);
        CHECK(active_message.flags == MIPI_DSI_MSG_LASTCOMMAND);
        if (lengths[i] > 2) {
            CHECK(last_packet.payload_length == 4);
            CHECK(last_packet.header[1] == 4 && last_packet.header[2] == 0);
        } else {
            CHECK(last_packet.payload_length == 0);
            CHECK(last_packet.header[1] == (lengths[i] ? 0x80 : 0));
            CHECK(last_packet.header[2] == (lengths[i] > 1 ? 0x12 : 0));
        }
        snprintf(name, sizeof(name), "packet 0x%02x full transfer payload and delay", types[i]);
        reset_fixture(name);
        seq.cmd_cnt = 1;
        cmds[0].header.data_type = types[i];
        cmds[0].header.payload_length = lengths[i];
        enum operation op = i < 4 ? GENERIC : DCS;
        CHECK(panel_simple_xfer_dsi_cmd_seq(&panel, &seq) == 0);
        ORDER(op, SLEEP);
        CHECK(events[0].arg == lengths[i] && events[0].extra == 1);
        CHECK(memcmp(events[0].bytes, payloads[0], lengths[i]) == 0);
        CHECK(events[1].arg == 3000 && events[1].extra == 3100);
        snprintf(name, sizeof(name), "packet 0x%02x errno stops sequence before delay", types[i]);
        reset_fixture(name);
        cmds[0].header.data_type = types[i];
        cmds[0].header.payload_length = lengths[i];
        inject(op, 1, -ETIMEDOUT);
        CHECK(panel_simple_xfer_dsi_cmd_seq(&panel, &seq) == -ETIMEDOUT);
        ORDER(op);
    }
    for (int position = 0; position < 3; position++) {
        char name[80];
        snprintf(name, sizeof(name), "transfer errno at init position %d stops successors", position);
        reset_fixture(name);
        inject(position == 1 ? DCS : GENERIC, position == 2 ? 2 : 1, -EHOSTDOWN);
        CHECK(panel_simple_xfer_dsi_cmd_seq(&panel, &seq) == -EHOSTDOWN);
        CHECK(event_count == position * 2 + 1);
    }
    reset_fixture("compression zero return is success");
    seq.cmd_cnt = 1;
    cmds[0].header.data_type = 0x07;
    cmds[0].header.payload_length = 1;
    CHECK(panel_simple_xfer_dsi_cmd_seq(&panel, &seq) == 0);
    ORDER(COMPRESSION, SLEEP);
    CHECK(events[0].arg == 1 && events[0].extra == 1);
    reset_fixture("compression errno stops sequence");
    cmds[0].header.data_type = 0x07;
    cmds[0].header.payload_length = 1;
    inject(COMPRESSION, 1, -EPIPE);
    CHECK(panel_simple_xfer_dsi_cmd_seq(&panel, &seq) == -EPIPE);
    ORDER(COMPRESSION);
    static u8 pps_bytes[128];
    for (int i = 0; i < 128; i++) pps_bytes[i] = i;
    reset_fixture("PPS zero return is success with exact payload");
    seq.cmd_cnt = 1;
    cmds[0].header.data_type = 0x0a;
    cmds[0].header.payload_length = 128;
    cmds[0].payload = pps_bytes;
    CHECK(panel_simple_xfer_dsi_cmd_seq(&panel, &seq) == 0);
    ORDER(ALLOCATION, PPS, SLEEP);
    CHECK(memcmp(events[1].bytes, pps_bytes, 128) == 0);
    reset_fixture("PPS errno stops sequence");
    cmds[0].header.data_type = 0x0a;
    cmds[0].header.payload_length = 128;
    cmds[0].payload = pps_bytes;
    inject(PPS, 1, -EPIPE);
    CHECK(panel_simple_xfer_dsi_cmd_seq(&panel, &seq) == -EPIPE);
    ORDER(ALLOCATION, PPS);
    reset_fixture("PPS allocation errno avoids transfer");
    cmds[0].header.data_type = 0x0a;
    cmds[0].header.payload_length = 128;
    cmds[0].payload = pps_bytes;
    alloc_fail = true;
    CHECK(panel_simple_xfer_dsi_cmd_seq(&panel, &seq) == -ENOMEM);
    ORDER(ALLOCATION);
}
static void test_prepare(void)
{
    reset_fixture("prepare success preserves GPIO transfer and delay order");
    desc.init_seq = &seq;
    CHECK(panel_simple_prepare(&panel.base) == 0);
    CHECK(panel.prepared && supply_refs == 1);
    CHECK(marker_count == 1 && marker_prepared && marker_transfer_count == 3);
    ORDER(REG_ENABLE, ENABLE_ON, SLEEP, RESET_ON, SLEEP, RESET_OFF, SLEEP,
          GENERIC, SLEEP, DCS, SLEEP, GENERIC, SLEEP);
    CHECK(events[2].arg == 11000 && events[4].arg == 13000 && events[6].arg == 17000);
    int before = event_count;
    CHECK(panel_simple_prepare(&panel.base) == 0);
    CHECK(event_count == before && supply_refs == 1);
    CHECK(marker_count == 1);
    reset_fixture("no HPD delay remains additive");
    panel.no_hpd = true;
    CHECK(panel_simple_prepare(&panel.base) == 0);
    CHECK(events[2].arg == 18000);
    reset_fixture("optional NULL enable and reset GPIO supported");
    panel.enable_gpio = panel.reset_gpio = NULL;
    CHECK(panel_simple_prepare(&panel.base) == 0);
    ORDER(REG_ENABLE, SLEEP, SLEEP, SLEEP);
    reset_fixture("regulator enable errno does not touch GPIO or disable unowned supply");
    inject(REG_ENABLE, 1, -EPROBE_DEFER);
    CHECK(panel_simple_prepare(&panel.base) == -EPROBE_DEFER);
    ORDER(REG_ENABLE);
    CHECK(!panel.prepared && supply_refs == 0);
    const enum operation gpio_ops[] = {ENABLE_ON, RESET_ON, RESET_OFF};
    for (int i = 0; i < 3; i++) {
        char name[80];
        snprintf(name, sizeof(name), "prepare GPIO stage %d errno unwinds supply", i);
        reset_fixture(name);
        desc.init_seq = &seq;
        inject(gpio_ops[i], 1, -ENXIO);
        CHECK(panel_simple_prepare(&panel.base) == -ENXIO);
        CHECK(!panel.prepared && supply_refs == 0);
        CHECK(occurrences[GENERIC] == 0 && occurrences[DCS] == 0);
        CHECK(events[event_count - 3].op == RESET_ON);
        CHECK(events[event_count - 2].op == ENABLE_OFF);
        CHECK(events[event_count - 1].op == REG_DISABLE);
    }
    for (int position = 0; position < 3; position++) {
        char name[80];
        snprintf(name, sizeof(name), "prepare DSI init errno at position %d unwinds and allows clean retry", position);
        reset_fixture(name);
        desc.init_seq = &seq;
        inject(position == 1 ? DCS : GENERIC, position == 2 ? 2 : 1, -EHOSTDOWN);
        CHECK(panel_simple_prepare(&panel.base) == -EHOSTDOWN);
        CHECK(!panel.prepared && supply_refs == 0);
        CHECK(occurrences[GENERIC] + occurrences[DCS] == position + 1);
        CHECK(marker_count == 0);
        CHECK(panel_simple_enable(&panel.base) == -EINVAL);
        injection_count = 0;
        CHECK(panel_simple_prepare(&panel.base) == 0);
        CHECK(panel.prepared && supply_refs == 1);
        CHECK(marker_count == 1 && marker_prepared);
    }
    const enum operation cleanup_ops[] = {RESET_ON, ENABLE_OFF, REG_DISABLE};
    for (int i = 0; i < 3; i++) {
        char name[80];
        snprintf(name, sizeof(name), "rollback error stage %d preserves primary errno and latches fault", i);
        reset_fixture(name);
        desc.init_seq = &seq;
        inject(DCS, 1, -ETIMEDOUT);
        inject(cleanup_ops[i], i == 0 ? 2 : 1, -ENOSPC);
        CHECK(panel_simple_prepare(&panel.base) == -ETIMEDOUT);
        CHECK(events[event_count - 1].op == REG_DISABLE);
        reject_after_fault();
    }
    reset_fixture("HPD optional lookup failure unwinds and preserves errno");
    panel.hpd_gpio = ERR_PTR(-EPROBE_DEFER);
    hpd_lookup_error = -EPROBE_DEFER;
    CHECK(panel_simple_prepare(&panel.base) == -EPROBE_DEFER);
    CHECK(!panel.prepared && supply_refs == 0);
    CHECK(occurrences[HPD_GET] == 1 && occurrences[HPD_READ] == 0);
    CHECK(events[event_count - 1].op == REG_DISABLE);
    reset_fixture("HPD read errno unwinds");
    panel.hpd_gpio = &hpd_gpio;
    hpd_value = -EREMOTEIO;
    CHECK(panel_simple_prepare(&panel.base) == -EREMOTEIO);
    CHECK(!panel.prepared && supply_refs == 0);
    reset_fixture("HPD timeout unwinds");
    panel.hpd_gpio = &hpd_gpio;
    hpd_value = 0;
    CHECK(panel_simple_prepare(&panel.base) == -ETIMEDOUT);
    CHECK(!panel.prepared && supply_refs == 0);
    reset_fixture("HPD deferred lookup then asserted prepare succeeds");
    panel.hpd_gpio = ERR_PTR(-EPROBE_DEFER);
    CHECK(panel_simple_prepare(&panel.base) == 0);
    CHECK(panel.prepared && supply_refs == 1);
    CHECK(events[3].op == HPD_GET && events[4].op == HPD_READ);
    reset_fixture("SPI init errno retained with complete unwind");
    desc.cmd_type = CMD_TYPE_SPI;
    desc.init_seq = &seq;
    inject(SPI, 1, -EPIPE);
    CHECK(panel_simple_prepare(&panel.base) == -EPIPE);
    CHECK(!panel.prepared && supply_refs == 0 && occurrences[SPI] == 1);
    CHECK(events[event_count - 1].op == REG_DISABLE);
}
static void test_unprepare(void)
{
    reset_fixture("unprepare success preserves exit reset supply and delay order");
    panel.prepared = true;
    supply_refs = 1;
    desc.exit_seq = &seq;
    CHECK(panel_simple_unprepare(&panel.base) == 0);
    CHECK(!panel.prepared && supply_refs == 0);
    ORDER(GENERIC, SLEEP, DCS, SLEEP, GENERIC, SLEEP, RESET_ON, ENABLE_OFF, REG_DISABLE, SLEEP);
    CHECK(events[9].arg == 29000);
    int before = event_count;
    CHECK(panel_simple_unprepare(&panel.base) == 0);
    CHECK(event_count == before && supply_refs == 0);
    reset_fixture("unprepared idle is idempotent without IO");
    CHECK(panel_simple_unprepare(&panel.base) == 0);
    CHECK(event_count == 0);
    for (int position = 0; position < 3; position++) {
        char name[80];
        snprintf(name, sizeof(name), "exit DSI errno at position %d still closes independent resources", position);
        reset_fixture(name);
        panel.prepared = true;
        supply_refs = 1;
        desc.exit_seq = &seq;
        inject(position == 1 ? DCS : GENERIC, position == 2 ? 2 : 1, -ETIMEDOUT);
        CHECK(panel_simple_unprepare(&panel.base) == -ETIMEDOUT);
        CHECK(!panel.prepared && supply_refs == 0);
        CHECK(occurrences[GENERIC] + occurrences[DCS] == position + 1);
        CHECK(occurrences[RESET_ON] == 1 && occurrences[ENABLE_OFF] == 1);
        CHECK(occurrences[REG_DISABLE] == 1);
        injection_count = 0;
        CHECK(panel_simple_prepare(&panel.base) == 0);
        CHECK(supply_refs == 1);
    }
    const enum operation cleanup_ops[] = {RESET_ON, ENABLE_OFF, REG_DISABLE};
    for (int i = 0; i < 3; i++) {
        char name[80];
        snprintf(name, sizeof(name), "unprepare shutdown errno stage %d latches unsafe lifecycle", i);
        reset_fixture(name);
        panel.prepared = true;
        supply_refs = 1;
        inject(cleanup_ops[i], 1, -EREMOTEIO);
        CHECK(panel_simple_unprepare(&panel.base) == -EREMOTEIO);
        ORDER(RESET_ON, ENABLE_OFF, REG_DISABLE, SLEEP);
        reject_after_fault();
    }
    reset_fixture("exit and three cleanup failures preserve first errno");
    panel.prepared = true;
    supply_refs = 1;
    desc.exit_seq = &seq;
    inject(GENERIC, 1, -EPIPE);
    inject(RESET_ON, 1, -ENOSPC);
    inject(ENABLE_OFF, 1, -ENXIO);
    inject(REG_DISABLE, 1, -EREMOTEIO);
    CHECK(panel_simple_unprepare(&panel.base) == -EPIPE);
    ORDER(GENERIC, RESET_ON, ENABLE_OFF, REG_DISABLE, SLEEP);
    reject_after_fault();
    reset_fixture("SPI exit errno no longer skips independent shutdown");
    panel.prepared = true;
    supply_refs = 1;
    desc.cmd_type = CMD_TYPE_SPI;
    desc.exit_seq = &seq;
    inject(SPI, 1, -EHOSTDOWN);
    CHECK(panel_simple_unprepare(&panel.base) == -EHOSTDOWN);
    CHECK(!panel.prepared && supply_refs == 0 && occurrences[SPI] == 1);
    ORDER(SPI, RESET_ON, ENABLE_OFF, REG_DISABLE, SLEEP);
    reset_fixture("optional NULL shutdown GPIO supported");
    panel.prepared = true;
    supply_refs = 1;
    panel.reset_gpio = panel.enable_gpio = NULL;
    CHECK(panel_simple_unprepare(&panel.base) == 0);
    ORDER(REG_DISABLE, SLEEP);
    reset_fixture("shutdown failure clears stale enabled state");
    panel.prepared = panel.enabled = true;
    supply_refs = 1;
    inject(ENABLE_OFF, 1, -EPIPE);
    CHECK(panel_simple_unprepare(&panel.base) == -EPIPE);
    reject_after_fault();
}
static void test_board_initialization(void)
{
    reset_fixture("board 180 command sequence fully accepted by real DW host");
    desc.init_seq = &board_seq;
    dsi.mode_flags = MIPI_DSI_MODE_LPM;
    CHECK(panel_simple_prepare(&panel.base) == 0);
    CHECK(panel.prepared && !panel.enabled && supply_refs == 1);
    CHECK(occurrences[GENERIC] == 178 && occurrences[DCS] == 2);
    CHECK(marker_count == 1 && marker_prepared && marker_transfer_count == 180);
    CHECK(active_message.flags == (MIPI_DSI_MSG_LASTCOMMAND | MIPI_DSI_MSG_USE_LPM));
    CHECK(last_packet.size == 4); /* Last DCS short command, one byte encoded in header. */
    CHECK(panel_simple_unprepare(&panel.base) == 0);
    CHECK(!panel.prepared && supply_refs == 0);
    int generic_index = 0, dcs_index = 0;
    for (int position = 0; position < 180; position++) {
        char name[80];
        snprintf(name, sizeof(name), "board init transfer %d errno stops successors and success marker", position);
        reset_fixture(name);
        desc.init_seq = &board_seq;
        dsi.mode_flags = MIPI_DSI_MODE_LPM;
        u8 type = board_cmds[position].header.data_type;
        bool is_dcs = type == 0x05 || type == 0x15 || type == 0x39;
        int ordinal = is_dcs ? ++dcs_index : ++generic_index;
        inject(is_dcs ? DCS : GENERIC, ordinal, -ETIMEDOUT);
        CHECK(panel_simple_prepare(&panel.base) == -ETIMEDOUT);
        CHECK(!panel.prepared && !panel.enabled && supply_refs == 0);
        CHECK(occurrences[GENERIC] + occurrences[DCS] == position + 1);
        CHECK(marker_count == 0);
        CHECK(events[event_count - 3].op == RESET_ON);
        CHECK(events[event_count - 2].op == ENABLE_OFF);
        CHECK(events[event_count - 1].op == REG_DISABLE);
        int before = event_count;
        CHECK(panel_simple_enable(&panel.base) == -EINVAL);
        CHECK(event_count == before);
    }
}
static void test_enable_and_regulators(void)
{
    reset_fixture("unprepared panel cannot enable");
    CHECK(panel_simple_enable(&panel.base) == -EINVAL);
    CHECK(!panel.enabled && event_count == 0);
    reset_fixture("enable success delay and idempotence preserved");
    panel.prepared = true;
    CHECK(panel_simple_enable(&panel.base) == 0);
    CHECK(panel.enabled);
    ORDER(SLEEP);
    CHECK(events[0].arg == 19000 && events[0].extra == 19100);
    CHECK(panel_simple_enable(&panel.base) == 0);
    CHECK(event_count == 1);
    CHECK(panel_simple_disable(&panel.base) == 0);
    CHECK(!panel.enabled && events[1].arg == 23000);
    CHECK(panel_simple_disable(&panel.base) == 0);
    CHECK(event_count == 2);
    reset_fixture("normal regulator disable errno propagated");
    supply_refs = 1;
    inject(REG_DISABLE, 1, -EREMOTEIO);
    CHECK(panel_simple_regulator_disable(&panel) == -EREMOTEIO);
    CHECK(supply_refs == 1);
    reset_fixture("inverted enable disables enabled supply");
    panel.power_invert = true;
    supply_refs = 1;
    CHECK(panel_simple_regulator_enable(&panel) == 0);
    ORDER(REG_STATUS, REG_DISABLE);
    CHECK(supply_refs == 0);
    reset_fixture("inverted enable preserves disable errno");
    panel.power_invert = true;
    supply_refs = 1;
    inject(REG_DISABLE, 1, -EPIPE);
    CHECK(panel_simple_regulator_enable(&panel) == -EPIPE);
    reset_fixture("inverted enable preserves status errno without writes");
    panel.power_invert = true;
    inject(REG_STATUS, 1, -ENXIO);
    CHECK(panel_simple_regulator_enable(&panel) == -ENXIO);
    ORDER(REG_STATUS);
    reset_fixture("inverted enable already off avoids duplicate disable");
    panel.power_invert = true;
    CHECK(panel_simple_regulator_enable(&panel) == 0);
    ORDER(REG_STATUS);
    reset_fixture("inverted disable enables off supply");
    panel.power_invert = true;
    CHECK(panel_simple_regulator_disable(&panel) == 0);
    ORDER(REG_STATUS, REG_ENABLE);
    CHECK(supply_refs == 1);
    reset_fixture("inverted disable preserves enable errno");
    panel.power_invert = true;
    inject(REG_ENABLE, 1, -EPIPE);
    CHECK(panel_simple_regulator_disable(&panel) == -EPIPE);
    reset_fixture("inverted disable preserves status errno without writes");
    panel.power_invert = true;
    inject(REG_STATUS, 1, -ENXIO);
    CHECK(panel_simple_regulator_disable(&panel) == -ENXIO);
    ORDER(REG_STATUS);
    reset_fixture("inverted disable already on avoids duplicate enable");
    panel.power_invert = true;
    supply_refs = 1;
    CHECK(panel_simple_regulator_disable(&panel) == 0);
    ORDER(REG_STATUS);
    CHECK(supply_refs == 1);
    reset_fixture("loader protection enable failure leaves flags false");
    inject(REG_ENABLE, 1, -EPIPE);
    CHECK(panel_simple_loader_protect(&panel.base) == -EPIPE);
    CHECK(!panel.prepared && !panel.enabled);
}
int main(void)
{
    test_transfers();
    test_prepare();
    test_board_initialization();
    test_unprepare();
    test_enable_and_regulators();
    if (this_failed) failed++;
    printf("{\"total\":%d,\"passed\":%d,\"failed\":%d,\"failures\":[", tests, tests - failed, failed);
    for (int i = 0; i < failure_count; i++) printf("%s\"%s\"", i ? "," : "", failures[i]);
    puts("]}");
    return failed ? 1 : 0;
}
