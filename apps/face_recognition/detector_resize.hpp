#pragma once
#include <opencv2/core.hpp>
namespace rtctrl::face {
// Full 320x320 letterbox. Only the verified OpenCV 3.4.5, 960-wide
// landscape case uses the equivalent fixed-point specialization.
// Other dimensions/builds retain cv::resize(INTER_LINEAR).
cv::Mat detector_letterbox(const cv::Mat& bgr, int width, int height);
} // namespace rtctrl::face
