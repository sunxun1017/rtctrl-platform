#ifndef RTCTRL_VISION_SYNTHETIC_CAPTURE_H
#define RTCTRL_VISION_SYNTHETIC_CAPTURE_H
#include "rtctrl/capture/capture_backend.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Deterministic, unpaced GRAY8 source. No device, OS clock, or vendor dependency.
 * Frames have sequence numbers; timestamps are zero (unavailable). */
struct rtctrl_synthetic_config {
    uint32_t width;
    uint32_t height;
};
const struct rtctrl_capture_backend* rtctrl_synthetic_backend(void);
int rtctrl_synthetic_open(const struct rtctrl_synthetic_config* config,
                          struct rtctrl_camera** camera);
#ifdef __cplusplus
}
#endif
#endif
