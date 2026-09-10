#include "rtctrl/adapters/synthetic/capture.h"
#include <errno.h>
#include <stdlib.h>
#include <string.h>
struct synthetic_camera {
    struct rtctrl_camera_format format;
    unsigned char* pixels;
    size_t size;
    uint32_t sequence;
};
static int synthetic_open(const void* config, void** output) {
    const struct rtctrl_synthetic_config* cfg = config;
    *output = NULL;
    if (!cfg || !cfg->width || !cfg->height || cfg->width > 4096 ||
        cfg->height > 4096) {
        return -EINVAL;
    }
    struct synthetic_camera* c = calloc(1, sizeof(*c));
    if (!c) {
        return -ENOMEM;
    }
    c->size = (size_t)cfg->width * cfg->height;
    c->pixels = malloc(c->size);
    if (!c->pixels) {
        free(c);
        return -ENOMEM;
    }
    c->format.width = cfg->width;
    c->format.height = cfg->height;
    c->format.plane_count = 1;
    c->format.pixel_format = RTCTRL_PIXEL_GRAY8;
    c->format.quantization = RTCTRL_RANGE_FULL;
    *output = c;
    return 0;
}
static int synthetic_format(const void* context,
                            struct rtctrl_camera_format* format) {
    const struct synthetic_camera* c = context;
    *format = c->format;
    return 0;
}
static int
synthetic_acquire(void* context, int timeout_ms, struct rtctrl_camera_frame* frame) {
    (void)timeout_ms;
    struct synthetic_camera* c = context;
    memset(frame, 0, sizeof(*frame));
    ++c->sequence;
    memset(c->pixels, (int)(c->sequence & 255U), c->size);
    frame->format = c->format;
    frame->sequence = c->sequence;
    frame->planes[0] =
        (struct rtctrl_frame_plane){c->pixels, c->size, c->format.width};
    return 0;
}
static int synthetic_release(void* context, uint64_t token) {
    (void)context;
    (void)token;
    return 0;
}
static int synthetic_close(void* context) {
    struct synthetic_camera* c = context;
    free(c->pixels);
    free(c);
    return 0;
}
const struct rtctrl_capture_backend* rtctrl_synthetic_backend(void) {
    static const struct rtctrl_capture_backend backend = {1,
                                                          synthetic_open,
                                                          synthetic_format,
                                                          synthetic_acquire,
                                                          synthetic_release,
                                                          synthetic_close};
    return &backend;
}
int rtctrl_synthetic_open(const struct rtctrl_synthetic_config* config,
                          struct rtctrl_camera** camera) {
    return rtctrl_camera_create(rtctrl_synthetic_backend(), config, camera);
}
