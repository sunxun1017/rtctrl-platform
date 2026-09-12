#pragma once
#include "video_frame.hpp"
#include <memory>
namespace rtctrl::face {
// One owner thread; staging buffers are internal, returned pixels are owned.
// RGA default interpolation differs from the CPU nearest-neighbor path.
class RgaFrameConverter {
  public:
    RgaFrameConverter();
    ~RgaFrameConverter();
    RgaFrameConverter(const RgaFrameConverter&) = delete;
    RgaFrameConverter& operator=(const RgaFrameConverter&) = delete;
    cv::Mat
    convert(const rtctrl_camera_frame& frame, int max_width, VideoColor color = {});
    static bool compiled();

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace rtctrl::face
