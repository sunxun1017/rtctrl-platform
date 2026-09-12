#pragma once
#include "rtctrl/capture/capture.h"
#include <opencv2/core.hpp>
namespace rtctrl::face {
// Overrides are only used when explicitly selected by the operator.
struct VideoColor {
    unsigned matrix = RTCTRL_YCBCR_UNKNOWN;
    unsigned range = RTCTRL_RANGE_UNKNOWN;
};
// Produces owned BGR pixels. No borrowed camera pointer escapes this call.
cv::Mat video_frame_bgr(const rtctrl_camera_frame& frame,
                        int max_width,
                        VideoColor color = {});
} // namespace rtctrl::face
