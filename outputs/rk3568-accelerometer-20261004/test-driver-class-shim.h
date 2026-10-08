#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define __init
#define __exit
#define THIS_MODULE NULL
#define KERN_ERR ""
#define printk(...) do { } while (0)
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((intptr_t)(p))
struct class { int unused; };
struct class_attribute { int id; };
static struct class class_object;
static struct class *sensor_class;
static struct class_attribute class_attr_accel_calibration = {1};
static struct class_attribute class_attr_gyro_calibration = {2};
static int create_fault, attr_fault, creates, attrs, removes, destroys, invalid;
static int removed_ids[2];
static struct class *class_create(void *owner, const char *name)
{
    creates++;
    return create_fault ? (struct class *)(intptr_t)create_fault : &class_object;
}
static int class_create_file(struct class *c, struct class_attribute *attr)
{
    attrs++;
    if (IS_ERR(c) || !c) {
        invalid++;
        return -EINVAL;
    }
    return attr_fault == attr->id ? -EIO : 0;
}
static void class_remove_file(struct class *c, struct class_attribute *attr)
{
    if (IS_ERR(c) || !c) {
        invalid++;
    }
    if (removes < 2) {
        removed_ids[removes] = attr->id;
    }
    removes++;
}
static void class_destroy(struct class *c)
{
    invalid += IS_ERR(c) || !c;
    destroys++;
}
