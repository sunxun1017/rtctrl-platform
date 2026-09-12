#include "capture_cli.h"
#include "rtctrl/adapters/v4l2/capture.h"
#include <stdio.h>
#include <string.h>
int main(int argc, char** argv) {
    if (argc < 2 || argc > 3 || strcmp(argv[1], "--help") == 0) {
        fprintf(stderr,
                "Usage: %s DEVICE [OUTPUT_FILE]\nPreserves V4L2 format; captures 70 "
                "frames.\n",
                argv[0]);
        return argc == 2 && strcmp(argv[1], "--help") == 0 ? 0 : 2;
    }
    rtctrl_capture_prepare_signals();
    struct rtctrl_camera* camera = NULL;
    const struct rtctrl_v4l2_config config = {argv[1], 0, 0, 0, 4};
    const int result =
        rtctrl_v4l2_open(&config, &camera); // 这个就是真正的注入依赖的函数
    if (result) {
        fprintf(stderr, "camera open: %s\n", strerror(-result));
        return 1;
    }
    return rtctrl_capture_run(camera, argc == 3 ? argv[2] : NULL);
}
