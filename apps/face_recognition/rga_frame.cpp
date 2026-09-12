#include "rga_frame.hpp"
#include <algorithm>
#include <cstring>
#include <stdexcept>
#include <vector>
#ifdef RTCTRL_HAVE_RGA
#include <im2d.h>
#endif
namespace rtctrl::face {
namespace {
void require(bool condition, const char* text) {
    if (!condition)
        throw std::runtime_error(text);
}
void plane(const rtctrl_frame_plane& p, size_t rows, size_t width) {
    require(p.data && rows && p.stride >= width && p.size >= width &&
                rows - 1 <= (p.size - width) / p.stride,
            "invalid/truncated RGA video plane");
    if (p.allocation_size)
        require(p.data_offset <= p.allocation_size &&
                    p.size <= p.allocation_size - p.data_offset,
                "invalid RGA video plane allocation/offset");
}
} // namespace
struct RgaFrameConverter::Impl {
#ifdef RTCTRL_HAVE_RGA
    struct Buffer {
        std::vector<unsigned char> bytes;
        rga_buffer_handle_t handle = 0;
        ~Buffer() {
            if (handle)
                releasebuffer_handle(handle);
        }
        void resize(size_t size) {
            if (handle && bytes.size() == size)
                return;
            if (handle) {
                releasebuffer_handle(handle);
                handle = 0;
            }
            bytes.resize(size);
            handle = importbuffer_virtualaddr(bytes.data(), static_cast<int>(size));
            require(handle != 0, "RGA staging virtual-address import failed");
        }
    } source, destination;
#endif
};
bool RgaFrameConverter::compiled() {
#ifdef RTCTRL_HAVE_RGA
    return true;
#else
    return false;
#endif
}
RgaFrameConverter::RgaFrameConverter()
    : impl_(std::make_unique<Impl>()) {
    require(compiled(),
            "RGA support not compiled; configure RTCTRL_RGA_INCLUDE_DIR and "
            "RTCTRL_RGA_LIBRARY or select cpu");
}
RgaFrameConverter::~RgaFrameConverter() = default;
cv::Mat RgaFrameConverter::convert(const rtctrl_camera_frame& f,
                                   int max_width,
                                   VideoColor color) {
    const auto w = f.format.width, h = f.format.height;
    const bool nv21 = f.format.pixel_format == RTCTRL_PIXEL_NV21;
    require(!f.corrupt && w && h && w <= 8192 && h <= 8192 && w % 2 == 0 &&
                h % 2 == 0 && max_width >= 2 && max_width <= 8192,
            "invalid RGA video dimensions/frame");
    require(f.format.pixel_format == RTCTRL_PIXEL_NV12 || nv21,
            "RGA supports NV12/NV21 only");
    require(f.format.plane_count == 1 || f.format.plane_count == 2,
            "RGA expects one or two planes");
    const unsigned matrix = color.matrix ? color.matrix : f.format.ycbcr_encoding;
    const unsigned range = color.range ? color.range : f.format.quantization;
    require(matrix == RTCTRL_YCBCR_BT601 || matrix == RTCTRL_YCBCR_BT709,
            "unknown/unsupported RGA YUV matrix: specify camera matrix explicitly");
    require(range == RTCTRL_RANGE_FULL || range == RTCTRL_RANGE_LIMITED,
            "unknown/unsupported RGA YUV range: specify camera range explicitly");
    const auto& p = f.planes[0];
    const auto* y = static_cast<const unsigned char*>(p.data);
    const unsigned char* uv;
    size_t uvstride;
    if (f.format.plane_count == 1) {
        plane(p, static_cast<size_t>(h) + h / 2, w);
        uv = y + static_cast<size_t>(p.stride) * h;
        uvstride = p.stride;
    } else {
        plane(p, h, w);
        plane(f.planes[1], h / 2, w);
        uv = static_cast<const unsigned char*>(f.planes[1].data);
        uvstride = f.planes[1].stride;
    }
#ifdef RTCTRL_HAVE_RGA
    const int ow = std::min(static_cast<int>(w), max_width);
    const int oh = std::max(1, static_cast<int>(static_cast<uint64_t>(h) * ow / w));
    // RGA pixel strides must meet hardware alignment even for odd output widths.
    const int src_stride = (static_cast<int>(w) + 15) & ~15;
    const int dst_stride = (ow + 15) & ~15;
    auto& source = impl_->source;
    auto& destination = impl_->destination;
    source.resize(static_cast<size_t>(src_stride) * h * 3 / 2);
    destination.resize(static_cast<size_t>(dst_stride) * oh * 3);
    for (unsigned row = 0; row < h; ++row)
        std::memcpy(source.bytes.data() + static_cast<size_t>(row) * src_stride,
                    y + static_cast<size_t>(row) * p.stride,
                    w);
    for (unsigned row = 0; row < h / 2; ++row)
        std::memcpy(source.bytes.data() + static_cast<size_t>(src_stride) * h +
                        static_cast<size_t>(row) * src_stride,
                    uv + static_cast<size_t>(row) * uvstride,
                    w);
    auto src =
        wrapbuffer_handle(source.handle,
                          w,
                          h,
                          nv21 ? RK_FORMAT_YCrCb_420_SP : RK_FORMAT_YCbCr_420_SP,
                          src_stride,
                          h);
    auto dst = wrapbuffer_handle(
        destination.handle, ow, oh, RK_FORMAT_BGR_888, dst_stride, oh);
    if (matrix == RTCTRL_YCBCR_BT601)
        dst.color_space_mode = range == RTCTRL_RANGE_FULL
                                   ? IM_YUV_TO_RGB_BT601_FULL
                                   : IM_YUV_TO_RGB_BT601_LIMIT;
    else if (range == RTCTRL_RANGE_LIMITED)
        dst.color_space_mode = IM_YUV_TO_RGB_BT709_LIMIT;
    else {
        src.color_space_mode = IM_YUV_BT709_FULL_RANGE;
        dst.color_space_mode = IM_RGB_FULL;
    }
    // Synchronous completion is required before reusing staging or releasing the
    // camera frame. DEFAULT interpolation is intentionally not called nearest.
    const auto status = imresize(src, dst, 0, 0, IM_INTERP_DEFAULT, 1);
    if (status != IM_STATUS_SUCCESS && status != IM_STATUS_NOERROR)
        throw std::runtime_error(std::string("RGA conversion failed: ") +
                                 imStrError(status));
    return cv::Mat(oh,
                   ow,
                   CV_8UC3,
                   destination.bytes.data(),
                   static_cast<size_t>(dst_stride) * 3)
        .clone();
#else
    (void)y;
    (void)uv;
    (void)uvstride;
    throw std::runtime_error("RGA support not compiled");
#endif
}
} // namespace rtctrl::face
