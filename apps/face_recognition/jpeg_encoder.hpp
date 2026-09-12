#pragma once
#include <memory>
#include <opencv2/core.hpp>
#include <string>
#include <vector>
namespace rtctrl::face {
// One owner thread. Every returned JPEG owns its bytes independently.
class JpegEncoder {
  public:
    explicit JpegEncoder(const std::string& encoder = "opencv",
                         const std::string& library = "libturbojpeg.so.0");
    ~JpegEncoder();
    JpegEncoder(const JpegEncoder&) = delete;
    JpegEncoder& operator=(const JpegEncoder&) = delete;
    std::vector<unsigned char> encode(const cv::Mat& bgr, int quality);
    static bool turbojpeg_compiled();

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace rtctrl::face
