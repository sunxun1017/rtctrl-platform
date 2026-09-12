#pragma once
#include "video_frame.hpp"
#include <memory>
namespace rtctrl::face {
// One owner thread; staging is default, direct DMA-BUF is explicit.
// Returned pixels are independently owned in either mode.
// RGA default interpolation differs from the CPU nearest-neighbor path.
class RgaFrameConverter {
  public:
    // Direct mode borrows DMA-BUFs from one fixed camera configuration.
    // Destroy this converter before closing/reconfiguring that camera.
    explicit RgaFrameConverter(bool direct_dmabuf = false);
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
