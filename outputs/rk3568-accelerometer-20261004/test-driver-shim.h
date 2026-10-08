#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define EXPORT_SYMBOL(x)
#define DBG(...) do { } while (0)
#define printk(...) do { } while (0)
#define dev_err(...) do { } while (0)
#define dev_info(...) do { } while (0)
#define pr_debug(...) do { } while (0)
#define BIT(x) (1U << (x))
#define SENSOR_OFF 0
#define SENSOR_ON 1
#define SENSOR_UNKNOW_DATA -1
#define IRQF_ONESHOT 1
#define ID_INVALID 0
#define ACCEL_ID_MXC6655XA 24
#define SENSOR_NUM_ID 128
#define SENSOR_TYPE_NULL 0
#define SENSOR_TYPE_ANGLE 1
#define SENSOR_TYPE_ACCEL 2
#define SENSOR_TYPE_COMPASS 3
#define SENSOR_TYPE_GYROSCOPE 4
#define SENSOR_TYPE_LIGHT 5
#define SENSOR_TYPE_PROXIMITY 6
#define SENSOR_TYPE_TEMPERATURE 7
#define SENSOR_TYPE_PRESSURE 8
#define SENSOR_NUM_TYPES 10
#define EPROBE_DEFER 517
#define I2C_M_RD 1
#define I2C_FUNC_I2C 1
#define GFP_KERNEL 0
#define EV_ABS 0
#define EV_REL 0
#define ABS_X 0
#define ABS_Y 1
#define ABS_Z 2
#define ABS_RX 3
#define ABS_RY 4
#define ABS_RZ 5
#define ABS_RUDDER 6
#define ABS_WHEEL 7
#define ABS_HAT0X 8
#define ABS_HAT0Y 9
#define ABS_BRAKE 10
#define ABS_MISC 11
#define ABS_TOOL_WIDTH 12
#define ABS_DISTANCE 13
#define ABS_THROTTLE 14
#define ABS_PRESSURE 15
#define REL_RX 0
#define REL_RY 1
#define REL_RZ 2
#define mutex_lock(x) do { } while (0)
#define mutex_unlock(x) do { } while (0)
#define mutex_init(x) do { } while (0)
#define atomic_set(x, y) (*(x) = (y))
#define init_waitqueue_head(x) do { } while (0)
#define set_bit(x, y) do { } while (0)
#define input_set_abs_params(...) do { } while (0)
#define input_set_capability(...) do { } while (0)

struct device_node { int unused; };
struct device { struct device_node *of_node; struct device *parent; };
struct i2c_adapter { struct device dev; };
struct i2c_client { struct device dev; struct i2c_adapter *adapter; int addr, flags, irq; void *data; };
struct i2c_device_id { char name[32]; unsigned long driver_data; };
struct i2c_msg { int addr, flags, len; unsigned char *buf; };
struct sensor_axis { int x, y, z; };
struct sensor_platform_data {
    int type, irq_pin, reset_pin, power_pin, irq_enable, poll_delay_ms;
    int x_min, y_min, z_min, factory, layout, power_off_in_suspend;
    unsigned char address; unsigned long irq_flags;
    signed char orientation[9]; int *project_name;
};
struct sensor_operate {
    char *name; int type, id_i2c, id_reg, id_data, ctrl_reg, ctrl_data;
    int range[2], brightness[2];
    int (*active)(struct i2c_client *, int, int);
    int (*init)(struct i2c_client *);
    int (*report)(struct i2c_client *);
};
struct input_dev { char *name; int evbit; struct device dev; };
struct sensor_private_data {
    struct i2c_client *client; struct sensor_platform_data *pdata;
    struct sensor_operate *ops; struct i2c_device_id *i2c_id;
    struct input_dev *input_dev; struct sensor_axis axis;
    int type, devid, status_cur, stop_work, is_factory, is_factory_ok, delaywork;
    int data_mutex, operation_mutex, sensor_mutex, i2c_mutex;
    struct { int m_flag, a_flag, mv_flag, open_flag, debug_flag, open_wq, delay; } flags;
    struct { struct device *parent; } miscdev;
};
enum of_gpio_flags { GPIO_UNUSED = 0 };
static struct sensor_operate *sensor_ops[SENSOR_NUM_ID];
static struct sensor_private_data *g_sensor[SENSOR_NUM_TYPES];
static int sensor_probe_times[SENSOR_NUM_ID];
static int transfer_result = 99, fault_call, calls, writes, init_fault, input_fault, misc_fault;
static int irq_calls, input_calls, enable_calls, work_inits, work_schedules;
static unsigned char registers[256];
static void *i2c_get_clientdata(struct i2c_client *c) { return c->data; }
static void i2c_set_clientdata(struct i2c_client *c, void *p) { c->data = p; }
static int i2c_transfer(struct i2c_adapter *a, struct i2c_msg *m, int n)
{
    (void)a;
    calls++;
    if (transfer_result != 99 && (fault_call == 0 || calls == fault_call)) {
        return transfer_result;
    }
    if (n == 2) {
        for (int i = 0; i < m[1].len; i++) {
            m[1].buf[i] = registers[(unsigned char)(m[0].buf[0] + i)];
        }
    } else if (!(m[0].flags & I2C_M_RD) && m[0].len >= 2) {
        registers[m[0].buf[0]] = m[0].buf[1];
        writes++;
    } else if (m[0].flags & I2C_M_RD) {
        m[0].buf[0] = registers[0];
    }
    return n;
}
static int i2c_check_functionality(struct i2c_adapter *a, int mask) { return 1; }
static void *devm_kzalloc(struct device *d, size_t n, int flags) { return calloc(1, n); }
static int of_property_read_u32(struct device_node *n, const char *key, int *v)
{
    *v = strcmp(key, "type") == 0 ? SENSOR_TYPE_ACCEL : 0;
    return 0;
}
static int of_property_read_u8(struct device_node *n, const char *key, unsigned char *v) { *v = 0; return 0; }
static int of_get_named_gpio_flags(struct device_node *n, const char *key, int index, enum of_gpio_flags *f) { *f = 0; return -1; }
static void *of_get_property(struct device_node *n, const char *key, int *v) { return NULL; }
static struct input_dev *devm_input_allocate_device(struct device *d) { return calloc(1, sizeof(struct input_dev)); }
static int input_register_device(struct input_dev *d) { input_calls++; return input_fault; }
static void sensor_delaywork_func(void *work) { }
static int sensor_interrupt(int irq, void *data) { return 0; }
#define INIT_DELAYED_WORK(work, fn) do { work_inits++; *(work) = 1; } while (0)
static int schedule_delayed_work(void *work, unsigned long delay) { work_schedules++; return 1; }
static int gpio_request(int gpio, const char *name) { return 0; }
static int gpio_to_irq(int gpio) { return gpio; }
static int devm_request_threaded_irq(struct device *d, int irq, void *primary,
                                    int (*thread)(int, void *), unsigned long flags,
                                    const char *name, void *data) { irq_calls++; return 0; }
static void disable_irq_nosync(int irq) { }
static int sensor_misc_device_register(struct sensor_private_data *s, int type) { return misc_fault; }
