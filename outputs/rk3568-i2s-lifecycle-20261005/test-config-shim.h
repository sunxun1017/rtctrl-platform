#include "test-lifecycle-shim.h"
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define EPROBE_DEFER 517
#define IORESOURCE_MEM 0x200
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((long)(intptr_t)(p))
#define ERR_PTR(e) ((void *)(intptr_t)(e))
struct device_node { const char *compatible; const char *extra; unsigned int trcm, bclk; bool missing_trcm, has_bclk; };
struct device_attribute { int unused; };
#define sysfs_emit(buf, ...) snprintf(buf, 4096, __VA_ARGS__)
static struct resource *platform_get_resource(struct platform_device *pdev, unsigned int type, unsigned int index) { return pdev->resource; }
static unsigned long resource_size(struct resource *resource) { return resource->end - resource->start + 1; }
static bool of_device_is_compatible(struct device_node *node, const char *compatible) { return !strcmp(node->compatible, compatible); }
static int of_property_read_u32(struct device_node *node, const char *name, unsigned int *value)
{
    if (!strcmp(name, "rockchip,clk-trcm")) { if (node->missing_trcm) return -EINVAL; *value = node->trcm; return 0; }
    if (!strcmp(name, "rockchip,bclk-fs")) { if (!node->has_bclk) return -EINVAL; *value = node->bclk; return 0; }
    return -EINVAL;
}
static bool of_property_read_bool(struct device_node *node, const char *name) { return node->extra && !strcmp(node->extra, name); }
static void *of_find_property(struct device_node *node, const char *name, void *length) { return of_property_read_bool(node, name) ? node : NULL; }
