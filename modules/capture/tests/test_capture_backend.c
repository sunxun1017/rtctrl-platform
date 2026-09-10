#include "rtctrl/adapters/synthetic/capture.h"
#include "rtctrl/capture/capture_backend.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures;
static void expect(int condition, const char* message) {
    if (!condition) {
        ++failures;
        fprintf(stderr, "%s\n", message);
    }
}
struct counters {
    unsigned closes, releases;
    uint64_t returned_token;
};
struct config {
    struct counters* counts;
    int fail_open, bad_format, bad_frame, fail_release, retry;
};
struct context {
    struct config config;
    unsigned char pixels[4];
    uint32_t sequence;
};
static int open_backend(const void* input, void** output) {
    struct context* c = calloc(1, sizeof(*c));
    if (!c) {
        return -ENOMEM;
    }
    c->config = *(const struct config*)input;
    *output = c;
    return c->config.fail_open ? -EIO : 0;
}
static int format_backend(const void* input, struct rtctrl_camera_format* format) {
    const struct context* c = input;
    memset(format, 0, sizeof(*format));
    format->width = format->height = 2;
    format->plane_count = 1;
    format->pixel_format = c->config.bad_format ? UINT32_MAX : RTCTRL_PIXEL_GRAY8;
    return 0;
}
static int
acquire_backend(void* input, int timeout, struct rtctrl_camera_frame* frame) {
    (void)timeout;
    struct context* c = input;
    if (c->config.retry) {
        c->config.retry = 0;
        return -EAGAIN;
    }
    format_backend(c, &frame->format);
    if (c->config.bad_frame) {
        frame->format.plane_count = RTCTRL_CAMERA_MAX_PLANES + 1;
    }
    frame->planes[0] = (struct rtctrl_frame_plane){c->pixels, sizeof(c->pixels), 2};
    frame->sequence = ++c->sequence;
    frame->token = 77; /* Backend tokens need not be globally monotonic. */
    return 0;
}
static int release_backend(void* input, uint64_t token) {
    struct context* c = input;
    ++c->config.counts->releases;
    c->config.counts->returned_token = token;
    return c->config.fail_release ? -EIO : 0;
}
static int close_backend(void* input) {
    struct context* c = input;
    ++c->config.counts->closes;
    free(c);
    return 0;
}
static struct rtctrl_capture_backend descriptor(void) {
    return (struct rtctrl_capture_backend){1,
                                           open_backend,
                                           format_backend,
                                           acquire_backend,
                                           release_backend,
                                           close_backend};
}
static void core_ownership(void) {
    struct counters counts = {0};
    struct config config = {&counts, 0, 0, 0, 0, 1};
    struct rtctrl_capture_backend backend = descriptor();
    struct rtctrl_camera* camera = NULL;
    expect(rtctrl_camera_create(&backend, &config, &camera) == 0,
           "inject independent backend");
    memset(&backend, 0, sizeof(backend)); /* No descriptor lifetime dependency. */
    struct rtctrl_camera_frame first, second;
    expect(rtctrl_camera_acquire(camera, 0, &first) == -EAGAIN,
           "transient backend error");
    expect(rtctrl_camera_acquire(camera, 0, &first) == 0,
           "transient error does not poison core");
    expect(rtctrl_camera_acquire(camera, 0, &second) == -EBUSY,
           "core enforces exclusive borrow");
    expect(rtctrl_camera_release(camera, first.token + 1) == -EINVAL &&
               counts.releases == 0,
           "bad public token never reaches adapter");
    expect(rtctrl_camera_release(camera, first.token) == 0 &&
               counts.returned_token == 77,
           "public token translated back to backend token");
    expect(rtctrl_camera_acquire(camera, 0, &second) == 0 &&
               second.token != first.token,
           "core generations distinguish reused backend tokens");
    expect(rtctrl_camera_release(camera, first.token) == -EINVAL,
           "stale token rejected");
    expect(rtctrl_camera_close(camera) == 0 && counts.closes == 1,
           "close outstanding borrow");
}
static void failures_cleanup(void) {
    struct counters counts = {0};
    struct config config = {&counts, 1, 0, 0, 0, 0};
    struct rtctrl_capture_backend backend = descriptor();
    struct rtctrl_camera* camera = NULL;
    expect(rtctrl_camera_create(&backend, &config, &camera) == -EIO && !camera &&
               counts.closes == 1,
           "failed open destroys partially created adapter context");
    config.fail_open = 0;
    config.bad_format = 1;
    expect(rtctrl_camera_create(&backend, &config, &camera) == -EPROTO && !camera &&
               counts.closes == 2,
           "invalid portable metadata rejected at creation");
    config.bad_format = 0;
    config.bad_frame = 1;
    expect(rtctrl_camera_create(&backend, &config, &camera) == 0,
           "open invalid-frame backend");
    struct rtctrl_camera_frame frame;
    expect(rtctrl_camera_acquire(camera, 0, &frame) == -EPROTO &&
               counts.releases == 1,
           "malformed frame is returned before poisoning handle");
    expect(rtctrl_camera_acquire(camera, 0, &frame) == -EIO,
           "poisoned handle cannot continue");
    expect(rtctrl_camera_close(camera) == 0, "close poisoned backend");
    config.bad_frame = 0;
    config.fail_release = 1;
    expect(rtctrl_camera_create(&backend, &config, &camera) == 0,
           "open release-failure backend");
    expect(rtctrl_camera_acquire(camera, 0, &frame) == 0,
           "borrow release-failure frame");
    expect(rtctrl_camera_release(camera, frame.token) == -EIO,
           "release failure propagated");
    expect(rtctrl_camera_acquire(camera, 0, &frame) == -EIO,
           "failed release invalidates core");
    expect(rtctrl_camera_close(camera) == 0, "release-failure cleanup");
    backend.version = 9;
    expect(rtctrl_camera_create(&backend, &config, &camera) == -EINVAL && !camera,
           "backend contract version checked");
}
static void synthetic(void) {
    struct rtctrl_camera* first = NULL;
    struct rtctrl_camera* second = NULL;
    const struct rtctrl_synthetic_config small = {8, 4}, large = {16, 8};
    expect(rtctrl_camera_create(rtctrl_synthetic_backend(), &small, &first) == 0,
           "same injection API opens synthetic source");
    expect(rtctrl_synthetic_open(&large, &second) == 0, "independent second camera");
    struct rtctrl_camera_frame frame;
    expect(rtctrl_camera_acquire(first, 0, &frame) == 0 &&
               frame.planes[0].size == 32 &&
               frame.format.pixel_format == RTCTRL_PIXEL_GRAY8 &&
               !frame.timestamp_monotonic &&
               ((const unsigned char*)frame.planes[0].data)[0] == 1,
           "deterministic portable frame");
    expect(rtctrl_camera_release(first, frame.token) == 0,
           "release synthetic frame");
    expect(rtctrl_camera_acquire(first, 0, &frame) == 0 && frame.sequence == 2 &&
               ((const unsigned char*)frame.planes[0].data)[0] == 2,
           "next synthetic frame");
    expect(rtctrl_camera_acquire(second, 0, &frame) == 0 && frame.sequence == 1 &&
               frame.planes[0].size == 128,
           "no global backend state");
    expect(rtctrl_camera_close(first) == 0 && rtctrl_camera_close(second) == 0,
           "close both cameras");
}
int main(void) {
    core_ownership();
    failures_cleanup();
    synthetic();
    return failures ? 1 : 0;
}
