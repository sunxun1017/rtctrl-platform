/* SPDX-License-Identifier: MIT */
/* Test-only kernel API boundary. Production function bodies are extracted verbatim. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/types.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
#define __packed __attribute__((packed))
#define CONFIG_DRM_MIPI_DSI 1
#define IS_ENABLED(x) (x)
#define GFP_KERNEL 0
#define GPIOD_IN 1
#define EPROBE_DEFER 517
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define container_of(p, t, m) ((t *)((char *)(p) - offsetof(t, m)))
#define EXPORT_SYMBOL(x)
#define dev_err(dev, ...) ((void)(dev))
#define dev_info(dev, ...) test_dev_info(dev)
#define BIT(n) (1UL << (n))
#define MIPI_DSI_MSG_USE_LPM BIT(1)
#define MIPI_DSI_MSG_LASTCOMMAND BIT(3)
#define MIPI_DSI_MODE_LPM BIT(11)
#define DSI_DEV_NAME_SIZE 20

struct device { int marker; };
struct drm_panel { struct device *dev; };
struct mipi_dsi_device;
struct mipi_dsi_host;
struct mipi_dsi_msg;
struct mipi_dsi_packet;
struct dw_mipi_dsi;
struct list_head { struct list_head *next, *prev; };
struct regulator { int marker; };
struct gpio_desc { int id; };
struct drm_display_mode { int marker; };
struct display_timing;
struct i2c_adapter;
struct drm_dsc_picture_parameter_set { u8 bytes[128]; };
enum drm_panel_orientation { ORIENTATION_UNKNOWN };

static int regulator_enable(struct regulator *r);
static void test_dev_info(struct device *dev);
static int regulator_disable(struct regulator *r);
static int regulator_is_enabled(struct regulator *r);
static int gpiod_direction_output(struct gpio_desc *g, int value);
static int gpiod_get_value_cansleep(struct gpio_desc *g);
static struct gpio_desc *devm_gpiod_get_optional(struct device *dev, const char *name, int flags);
static void usleep_range(unsigned long min, unsigned long max);
static void *devm_kzalloc(struct device *dev, size_t bytes, int flags);
ssize_t mipi_dsi_generic_write(struct mipi_dsi_device *dsi, const void *data, size_t len);
ssize_t mipi_dsi_dcs_write_buffer(struct mipi_dsi_device *dsi, const void *data, size_t len);
ssize_t mipi_dsi_compression_mode(struct mipi_dsi_device *dsi, bool enable);
ssize_t mipi_dsi_picture_parameter_set(struct mipi_dsi_device *dsi,
                                            const struct drm_dsc_picture_parameter_set *pps);
static void dw_mipi_message_config(struct dw_mipi_dsi *dsi, const struct mipi_dsi_msg *msg);
static int dw_mipi_dsi_write(struct dw_mipi_dsi *dsi, const struct mipi_dsi_packet *packet);
static int dw_mipi_dsi_read(struct dw_mipi_dsi *dsi, const struct mipi_dsi_msg *msg);
static int test_poll(int value, bool asserted);
#define readx_poll_timeout(op, arg, value, cond, sleep, timeout) \
    ((value) = op(arg), test_poll((value), !!(cond)))
