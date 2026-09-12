#pragma once
#include <memory>
#include <opencv2/core.hpp>
#include <vector>
namespace rtctrl::face {
// One owner thread. Hardware quality is not byte-equivalent to libjpeg quality.
class MppJpegEncoder {
  public:
    MppJpegEncoder();
    ~MppJpegEncoder();
    MppJpegEncoder(const MppJpegEncoder&) = delete;
    MppJpegEncoder& operator=(const MppJpegEncoder&) = delete;
    std::vector<unsigned char> encode(const cv::Mat& bgr, int quality);
    static bool compiled();

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace rtctrl::face
