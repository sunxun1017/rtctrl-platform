#include "rtctrl/vision/capture.h"

#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static volatile sig_atomic_t stopped;
static void stop_capture(int signal_number) {
    (void)signal_number;
    stopped = 1;
}

int main(int argc, char** argv) {
    if (argc < 2 || argc > 3 || strcmp(argv[1], "--help") == 0) {
        fprintf(
            stderr,
            "Usage: %s DEVICE [OUTPUT_FILE]\n"
            "Preserves negotiated device format; captures 70 frames.\n"
            "Optional output saves the first non-corrupt frame and JSON metadata.\n",
            argv[0]);
        return argc == 2 && strcmp(argv[1], "--help") == 0 ? 0 : 2;
    }
    signal(SIGINT, stop_capture);
    signal(SIGTERM, stop_capture);
    const struct rtctrl_camera_config config = {argv[1], 0, 0, 0, 4};
    struct rtctrl_camera* camera = NULL;
    int result = rtctrl_camera_open(&config, &camera);
    if (result) {
        fprintf(stderr, "camera open: %s\n", strerror(-result));
        return 1;
    }
    unsigned captured = 0, corrupt = 0;
    unsigned long long dropped = 0;
    uint32_t previous = 0;
    int saved = 0;
    while (!stopped && captured < 70) {
        struct rtctrl_camera_frame frame;
        result = rtctrl_camera_acquire(camera, 2000, &frame);
        if (result == -EAGAIN || result == -EINTR) {
            result = 0;
            continue;
        }
        if (result) {
            break;
        }
        if (captured && frame.sequence != previous + 1U) {
            const uint32_t gap = frame.sequence - previous - 1U;
            if (gap < UINT32_MAX / 2U) {
                dropped += gap;
            }
        }
        previous = frame.sequence;
        ++captured;
        if (frame.corrupt) {
            ++corrupt;
        }
        if (argc == 3 && !saved && !frame.corrupt) {
            FILE* output = fopen(argv[2], "wb");
            if (!output) {
                result = -errno;
            } else {
                for (uint32_t p = 0; p < frame.format.plane_count; ++p) {
                    if (fwrite(
                            frame.planes[p].data, 1, frame.planes[p].size, output) !=
                        frame.planes[p].size) {
                        result = -EIO;
                        break;
                    }
                }
                if (fclose(output) != 0) {
                    result = -EIO;
                }
            }
            char metadata_path[4096];
            const int length =
                snprintf(metadata_path, sizeof(metadata_path), "%s.json", argv[2]);
            if (!result && (length < 0 || (size_t)length >= sizeof(metadata_path))) {
                result = -ENAMETOOLONG;
            }
            if (!result) {
                FILE* metadata = fopen(metadata_path, "w");
                if (!metadata) {
                    result = -errno;
                } else {
                    fprintf(
                        metadata,
                        "{\"width\":%u,\"height\":%u,\"fourcc\":%u,\"sequence\":%u,"
                        "\"timestamp_ns\":%lld,\"timestamp_monotonic\":%d,"
                        "\"colorspace\":%u,"
                        "\"quantization\":%u,\"transfer_function\":%u,\"ycbcr_"
                        "encoding\":%u,\"planes\":[",
                        frame.format.width,
                        frame.format.height,
                        frame.format.fourcc,
                        frame.sequence,
                        (long long)frame.timestamp_ns,
                        frame.timestamp_monotonic,
                        frame.format.colorspace,
                        frame.format.quantization,
                        frame.format.transfer_function,
                        frame.format.ycbcr_encoding);
                    for (uint32_t p = 0; p < frame.format.plane_count; ++p) {
                        fprintf(metadata,
                                "%s{\"stride\":%u,\"size\":%zu}",
                                p ? "," : "",
                                frame.planes[p].stride,
                                frame.planes[p].size);
                    }
                    fprintf(metadata, "]}\n");
                    if (ferror(metadata)) {
                        result = -EIO;
                    }
                    if (fclose(metadata) != 0) {
                        result = -EIO;
                    }
                }
            }
            saved = !result;
        }
        const int released = rtctrl_camera_release(camera, frame.token);
        if (!result) {
            result = released;
        }
        if (result) {
            break;
        }
    }
    const int closed = rtctrl_camera_close(camera);
    if (!result) {
        result = closed;
    }
    if (!result && argc == 3 && !saved && !stopped) {
        result = -ENODATA;
    }
    fprintf(stderr,
            "frames=%u corrupt=%u dropped=%llu status=%s\n",
            captured,
            corrupt,
            dropped,
            result ? strerror(-result) : "ok");
    return result ? 1 : 0;
}
