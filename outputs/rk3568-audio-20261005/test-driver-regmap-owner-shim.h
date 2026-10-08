/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define GFP_KERNEL 0
#define EXPORT_SYMBOL_GPL(x)
#define WARN_ON(x) (x)
struct device { void *lookup; };
struct regmap_config { const char *name; };
struct mutex { int dummy; };
struct list_head { int dummy; };
struct regmap_bus { void (*free_context)(void *); };
struct regmap {
    struct device *dev;
    const char *name;
    struct regmap_bus *bus;
    void *bus_context;
    void *work_buf;
    struct list_head async_free;
    void *hwlock;
    void (*lock)(void *);
    struct mutex mutex;
    void *patch;
};
struct regmap_async { struct list_head list; void *work_buf; };
static int regmap_set_name(struct regmap *map, const struct regmap_config *config)
{
    map->name = strdup(config->name);
    return map->name ? 0 : -ENOMEM;
}
static void regmap_debugfs_exit(struct regmap *map) { }
static void regmap_debugfs_init(struct regmap *map) { }
static void regcache_exit(struct regmap *map) { }
static void regmap_range_exit(struct regmap *map) { }
static void dev_get_regmap_release(struct device *dev, void *res) { }
static void *devres_alloc(void (*action)(struct device *, void *), size_t size, int flags)
{
    return calloc(1, size);
}
static void devres_add(struct device *dev, void *resource) { dev->lookup = resource; }
static bool list_empty(struct list_head *list) { return true; }
#define list_first_entry_or_null(head, type, field) ((type *)NULL)
static void list_del(struct list_head *list) { }
static void kfree(void *data) { free(data); }
static void kfree_const(const void *data) { free((void *)data); }
static void hwspin_lock_free(void *lock) { }
static void regmap_lock_mutex(void *data) { }
static void mutex_destroy(struct mutex *mutex) { }
