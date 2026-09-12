#include "video_frame.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>
namespace rtctrl::face {
namespace {
void require(bool condition, const char* message) {
    if (!condition)
        throw std::runtime_error(message);
}
void plane_check(const rtctrl_frame_plane& p, size_t rows, size_t bytes) {
    require(p.data && rows && p.stride >= bytes, "invalid video plane stride/data");
    require(p.size >= bytes && rows - 1 <= (p.size - bytes) / p.stride,
            "truncated video plane");
}
unsigned char byte(float value) {
    return static_cast<unsigned char>(std::clamp(value + 0.5f, 0.0f, 255.0f));
}
} // namespace
cv::Mat
video_frame_bgr_scalar(const rtctrl_camera_frame& f, int max_width, VideoColor override) {
    auto w = f.format.width, h = f.format.height, fmt = f.format.pixel_format;
    require(!f.corrupt && w && h && w <= 8192 && h <= 8192 && max_width >= 2 &&
                max_width <= 8192,
            "invalid video dimensions/frame");
    bool nv = fmt == RTCTRL_PIXEL_NV12 || fmt == RTCTRL_PIXEL_NV21;
    bool rgb = fmt == RTCTRL_PIXEL_RGB24 || fmt == RTCTRL_PIXEL_BGR24;
    require(nv || rgb, "video supports NV12/NV21/RGB24/BGR24 only");
    require(f.format.plane_count >= 1 && f.format.plane_count <= 2,
            "unsupported video plane count");
    const auto& p = f.planes[0];
    const unsigned char* y = static_cast<const unsigned char*>(p.data);
    const unsigned char* uv = nullptr;
    size_t uvstride = 0;
    unsigned matrix = override.matrix ? override.matrix : f.format.ycbcr_encoding;
    unsigned range = override.range ? override.range : f.format.quantization;
    if (nv) {
        require(w % 2 == 0 && h % 2 == 0, "NV12/NV21 dimensions must be even");
        require(matrix == RTCTRL_YCBCR_BT601 || matrix == RTCTRL_YCBCR_BT709,
                "unknown/unsupported YUV matrix: specify --yuv-matrix bt601 or "
                "bt709 from camera configuration");
        require(range == RTCTRL_RANGE_FULL || range == RTCTRL_RANGE_LIMITED,
                "unknown YUV range: specify --yuv-range full or limited");
        if (f.format.plane_count == 1) {
            plane_check(p, static_cast<size_t>(h) + h / 2, w);
            uv = y + static_cast<size_t>(p.stride) * h;
            uvstride = p.stride;
        } else {
            plane_check(p, h, w);
            plane_check(f.planes[1], h / 2, w);
            uv = static_cast<const unsigned char*>(f.planes[1].data);
            uvstride = f.planes[1].stride;
        }
    } else {
        require(f.format.plane_count == 1, "RGB requires one plane");
        plane_check(p, h, static_cast<size_t>(w) * 3);
    }
    int ow = std::min(static_cast<int>(w), max_width);
    int oh = std::max(1, static_cast<int>(static_cast<uint64_t>(h) * ow / w));
    cv::Mat result(oh, ow, CV_8UC3);
    float kr = matrix == RTCTRL_YCBCR_BT709 ? 0.2126f : 0.299f;
    float kb = matrix == RTCTRL_YCBCR_BT709 ? 0.0722f : 0.114f;
    float kg = 1 - kr - kb;
    for (int row = 0; row < oh; ++row) {
        auto sy = static_cast<size_t>(row) * h / oh;
        auto* dst = result.ptr<cv::Vec3b>(row);
        for (int col = 0; col < ow; ++col) {
            auto sx = static_cast<size_t>(col) * w / ow;
            if (rgb) {
                const auto* pixel = y + sy * p.stride + sx * 3;
                dst[col] = fmt == RTCTRL_PIXEL_BGR24
                               ? cv::Vec3b(pixel[0], pixel[1], pixel[2])
                               : cv::Vec3b(pixel[2], pixel[1], pixel[0]);
            } else {
                auto offset = (sy / 2) * uvstride + (sx / 2) * 2;
                float u = uv[offset + (fmt == RTCTRL_PIXEL_NV21 ? 1 : 0)] - 128.0f;
                float v = uv[offset + (fmt == RTCTRL_PIXEL_NV21 ? 0 : 1)] - 128.0f;
                float luma = y[sy * p.stride + sx];
                if (range == RTCTRL_RANGE_LIMITED) {
                    luma = (luma - 16) * (255.0f / 219);
                    u *= 255.0f / 224;
                    v *= 255.0f / 224;
                }
                dst[col] = cv::Vec3b(byte(luma + 2 * (1 - kb) * u),
                                     byte(luma - 2 * kb * (1 - kb) / kg * u -
                                          2 * kr * (1 - kr) / kg * v),
                                     byte(luma + 2 * (1 - kr) * v));
            }
        }
    }
    return result;
}
} // namespace rtctrl::face
