#include "capture_cli.h"
#include "rtctrl/adapters/synthetic/capture.h"
#include <stdio.h>
#include <string.h>
int main(int argc, char** argv) {
    if (argc > 2 || (argc == 2 && strcmp(argv[1], "--help") == 0)) {
        fprintf(stderr,
                "Usage: %s [OUTPUT_FILE]\nCaptures 70 synthetic GRAY8 frames "
                "(64x48), without hardware.\n",
                argv[0]);
        return argc == 2 ? 0 : 2;
    }
    rtctrl_capture_prepare_signals();
    struct rtctrl_camera* camera = NULL;
    const struct rtctrl_synthetic_config config = {64, 48};
    const int result = rtctrl_synthetic_open(&config, &camera);
    if (result) {
        fprintf(stderr, "synthetic open: %s\n", strerror(-result));
        return 1;
    }
    return rtctrl_capture_run(camera, argc == 2 ? argv[1] : NULL);
}
