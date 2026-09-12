#include "rtctrl/adapters/v4l2/capture.h"
#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>

static int failures, opened, mapped, stream_off;
static int fail_mapping, invalid_metadata, fail_release, fail_stream_off;
static int dequeued;
static int exports, fail_export, invalid_export;
static int live[4], closed[4];
static unsigned offset;
static void* first_mapping;
static int export_fd(unsigned i) {
    return i ? 100 + (int)i : 0;
}
static void expect(int condition, const char* reason) {
    if (!condition) {
        ++failures;
        fprintf(stderr, "%s\n", reason);
    }
}
int __wrap_open(const char* path, int flags, ...) {
    (void)path;
    (void)flags;
    ++opened;
    return 42;
}
int __wrap_close(int fd) {
    if (fd != 42) {
        for (unsigned i = 0; i < 4; ++i)
            if (fd == export_fd(i)) {
                expect(live[i], "export closed once");
                live[i] = 0;
                ++closed[i];
                return 0;
            }
        expect(0, "unexpected close");
        return -1;
    }
    --opened;
    return 0;
}
void* __wrap_mmap(
    void* addr, size_t length, int prot, int flags, int fd, off_t offset) {
    (void)addr;
    (void)prot;
    (void)flags;
    (void)fd;
    (void)offset;
    if (fail_mapping && mapped == 1) {
        errno = ENOMEM;
        return MAP_FAILED;
    }
    void* p = malloc(length);
    if (p) {
        if (!mapped)
            first_mapping = p;
        ++mapped;
    }
    return p ? p : MAP_FAILED;
}
int __wrap_munmap(void* addr, size_t length) {
    (void)length;
    free(addr);
    --mapped;
    return 0;
}
int __wrap_poll(struct pollfd* fds, nfds_t count, int timeout) {
    (void)count;
    (void)timeout;
    fds[0].revents = POLLIN;
    return 1;
}
/* Fortified glibc builds may route poll through __poll_chk. Keep the
 * syscall fake effective under ASan/UBSan as well as release builds. */
int __wrap___poll_chk(struct pollfd* fds, nfds_t count, int timeout, size_t size) {
    (void)size;
    return __wrap_poll(fds, count, timeout);
}
int __wrap_ioctl(int fd, unsigned long request, ...) {
    (void)fd;
    va_list ap;
    va_start(ap, request);
    void* arg = va_arg(ap, void*);
    va_end(ap);
    if (request == VIDIOC_QUERYCAP) {
        struct v4l2_capability* c = arg;
        c->capabilities = V4L2_CAP_VIDEO_CAPTURE_MPLANE | V4L2_CAP_STREAMING;
    } else if (request == VIDIOC_G_FMT) {
        struct v4l2_format* f = arg;
        f->fmt.pix_mp.width = 16;
        f->fmt.pix_mp.height = 16;
        f->fmt.pix_mp.pixelformat = V4L2_PIX_FMT_NV12;
        f->fmt.pix_mp.num_planes = 1;
        f->fmt.pix_mp.plane_fmt[0].bytesperline = 16;
    } else if (request == VIDIOC_QUERYBUF) {
        struct v4l2_buffer* b = arg;
        b->m.planes[0].length = 384;
    } else if (request == VIDIOC_EXPBUF) {
        struct v4l2_exportbuffer* e = arg;
        ++exports;
        expect(e->type == V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE && e->index < 4 &&
                   e->plane == 0 && e->flags == (O_CLOEXEC | O_RDWR),
               "export arguments");
        if (exports == fail_export) {
            errno = ENOTTY;
            return -1;
        }
        if (exports == invalid_export) {
            e->fd = -1;
            return 0;
        }
        e->fd = export_fd(e->index);
        expect(!live[e->index], "new exported fd");
        live[e->index] = 1;
    } else if (request == VIDIOC_DQBUF) {
        struct v4l2_buffer* b = arg;
        b->index = 0;
        b->sequence = 5;
        b->m.planes[0].bytesused = invalid_metadata ? 1000 : 384;
        b->m.planes[0].data_offset = offset;
        b->flags = V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC;
        b->timestamp.tv_sec = 1;
        dequeued = 1;
    } else if (request == VIDIOC_QBUF && dequeued && fail_release) {
        errno = EIO;
        return -1;
    } else if (request == VIDIOC_STREAMOFF) {
        ++stream_off;
        if (fail_stream_off) {
            errno = EIO;
            return -1;
        }
    }
    return 0;
}
int main(void) {
    const struct rtctrl_v4l2_config cfg = {"fake", 0, 0, 0, 4};
    struct rtctrl_camera* camera = NULL;
    struct rtctrl_camera_frame frame;
    fail_mapping = 1;
    expect(rtctrl_v4l2_open(&cfg, &camera) == -ENOMEM && !camera,
           "partial mmap fails");
    expect(!opened && !mapped,
           "partial initialization releases mappings and device");
    fail_mapping = 0;
    expect(rtctrl_v4l2_open(&cfg, &camera) == 0, "open capture");
    expect(rtctrl_camera_acquire(camera, 0, &frame) == 0 &&
               frame.planes[0].size == 384 && frame.planes[0].stride == 16 &&
               frame.timestamp_monotonic,
           "frame contract");
    expect(rtctrl_camera_acquire(camera, 0, &frame) == -EBUSY,
           "one outstanding frame");
    expect(rtctrl_camera_release(camera, frame.token + 1) == -EINVAL,
           "reject wrong ownership token");
    expect(rtctrl_camera_release(camera, frame.token) == 0, "return frame");
    expect(rtctrl_camera_release(camera, frame.token) == -EINVAL,
           "reject double return");
    invalid_metadata = 1;
    expect(rtctrl_camera_acquire(camera, 0, &frame) == -EPROTO,
           "reject oversized driver payload");
    fail_stream_off = 1;
    expect(rtctrl_camera_close(camera) == -EIO && !opened && !mapped &&
               stream_off == 1,
           "cleanup completes despite STREAMOFF error");
    fail_stream_off = invalid_metadata = dequeued = 0;
    expect(rtctrl_v4l2_open(&cfg, &camera) == 0, "recreate capture after failure");
    expect(rtctrl_camera_acquire(camera, 0, &frame) == 0,
           "acquire after recreation");
    fail_release = 1;
    expect(rtctrl_camera_release(camera, frame.token) == -EIO,
           "report QBUF failure");
    expect(rtctrl_camera_acquire(camera, 0, &frame) == -EIO,
           "failed ownership handoff poisons handle");
    expect(rtctrl_camera_close(camera) == 0 && !opened && !mapped,
           "close failed handoff");
    expect(exports == 0, "MMAP default never exports");
    fail_release = dequeued = 0;
    struct rtctrl_v4l2_config exporting = cfg;
    exporting.export_dmabuf = 1;
    fail_export = 3;
    expect(rtctrl_v4l2_open(&exporting, &camera) == -ENOTTY && !camera,
           "required export failure");
    expect(!opened && !mapped && closed[0] == 1 && closed[1] == 1 && !closed[2] &&
               !live[0] && !live[1],
           "partial export cleanup includes fd zero");
    fail_export = exports = 0;
    invalid_export = 2;
    expect(rtctrl_v4l2_open(&exporting, &camera) == -EPROTO && !camera,
           "invalid exported fd");
    expect(!opened && !mapped && closed[0] == 2 && closed[1] == 1 && !live[0],
           "invalid export cleans earlier resources");
    invalid_export = exports = 0;
    offset = 16;
    expect(rtctrl_v4l2_open(&exporting, &camera) == 0 && exports == 4,
           "exports all buffers");
    expect(rtctrl_camera_acquire(camera, 0, &frame) == 0 &&
               frame.planes[0].dmabuf_valid && frame.planes[0].dmabuf_fd == 0 &&
               frame.planes[0].allocation_size == 384 &&
               frame.planes[0].data_offset == 16 && frame.planes[0].size == 368 &&
               frame.planes[0].data == (unsigned char*)first_mapping + 16,
           "fd zero and payload offset");
    expect(rtctrl_camera_release(camera, frame.token) == 0 && live[0] &&
               closed[0] == 2,
           "release does not close exporter descriptor");
    expect(rtctrl_camera_acquire(camera, 0, &frame) == 0 &&
               frame.planes[0].dmabuf_fd == 0,
           "next lease borrows same descriptor");
    expect(rtctrl_camera_close(camera) == 0 && !opened && !mapped,
           "close outstanding lease");
    expect(closed[0] == 3 && closed[1] == 2 && closed[2] == 1 && closed[3] == 1 &&
               !live[0] && !live[1] && !live[2] && !live[3],
           "close every export exactly once");
    return failures ? 1 : 0;
}
