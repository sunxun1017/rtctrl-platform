#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <linux/videodev2.h>

/* Isolated gst-launch experiment: expose all formats except NM12 on video31.
 * Do not alter S_FMT, buffer ownership, or any streaming ioctl. */
int ioctl(int fd, unsigned long request, ...)
{
    static int (*real_ioctl)(int, unsigned long, ...) = NULL;
    va_list ap;
    void *arg;
    if (!real_ioctl) real_ioctl = dlsym(RTLD_NEXT, "ioctl");
    va_start(ap, request); arg = va_arg(ap, void *); va_end(ap);
    const char *enabled = getenv("RTCTRL_SINGLE_NV12");
    if (request == VIDIOC_ENUM_FMT && enabled && !strcmp(enabled, "1")) {
        char path[64], target[128];
        snprintf(path, sizeof(path), "/proc/self/fd/%d", fd);
        ssize_t n = readlink(path, target, sizeof(target)-1);
        if (n >= 0) target[n] = 0;
        if (n >= 0 && !strcmp(target, "/dev/video31")) {
            struct v4l2_fmtdesc *out = arg, candidate;
            unsigned int requested = out->index, visible = 0;
            for (unsigned int actual = 0; actual < 256; ++actual) {
                candidate = *out; candidate.index = actual;
                int ret = real_ioctl(fd, request, &candidate);
                if (ret < 0) return ret;
                if (candidate.pixelformat == V4L2_PIX_FMT_NV12M) continue;
                if (visible++ == requested) {
                    *out = candidate; out->index = requested; return ret;
                }
            }
        }
    }
    return real_ioctl(fd, request, arg);
}
