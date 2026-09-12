#include "rga_frame.hpp"
#include <algorithm>
#include <cstring>
#include <limits>
#include <map>
#include <stdexcept>
#include <sys/stat.h>
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
    bool direct = false;
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
    struct Imported {
        rga_buffer_handle_t handle;
        dev_t device;
        ino_t inode;
        size_t allocation;
    };
    std::map<int, Imported> imported;
    unsigned width = 0, height = 0, stride = 0, format = 0;
    ~Impl() {
        for (const auto& item : imported)
            releasebuffer_handle(item.second.handle);
    }
    rga_buffer_handle_t direct_source(const rtctrl_camera_frame& f) {
        const auto& p = f.planes[0];
        require(f.format.plane_count == 1 && p.dmabuf_valid && p.dmabuf_fd >= 0 &&
                    p.data_offset == 0,
                "direct RGA requires one DMA-BUF plane with zero offset");
        require(p.stride >= f.format.width && p.stride % 16 == 0 && p.stride <= 8192,
                "direct RGA requires a valid aligned pixel stride");
        const size_t required = size_t(p.stride) * f.format.height * 3 / 2;
        require(p.size >= required && p.allocation_size >= required &&
                    p.allocation_size <= size_t(std::numeric_limits<int>::max()),
                "direct RGA allocation/payload is insufficient");
        require(!width || (width == f.format.width && height == f.format.height &&
                           stride == p.stride && format == f.format.pixel_format),
                "direct RGA camera layout changed; recreate converter");
        struct stat identity {};
        require(fstat(p.dmabuf_fd, &identity) == 0,
                "direct RGA cannot inspect DMA-BUF identity");
        auto found = imported.find(p.dmabuf_fd);
        if (found != imported.end()) {
            require(found->second.device == identity.st_dev &&
                        found->second.inode == identity.st_ino &&
                        found->second.allocation == p.allocation_size,
                    "direct RGA descriptor reused or allocation changed");
            return found->second.handle;
        }
        require(imported.size() < 32, "direct RGA buffer count exceeds limit");
        auto handle = importbuffer_fd(p.dmabuf_fd, int(p.allocation_size));
        require(handle != 0, "direct RGA DMA-BUF import failed");
        try {
            imported.emplace(
                p.dmabuf_fd,
                Imported{
                    handle, identity.st_dev, identity.st_ino, p.allocation_size});
        } catch (...) {
            releasebuffer_handle(handle);
            throw;
        }
        width = f.format.width;
        height = f.format.height;
        stride = p.stride;
        format = f.format.pixel_format;
        return handle;
    }
#endif
};
bool RgaFrameConverter::compiled() {
#ifdef RTCTRL_HAVE_RGA
    return true;
#else
    return false;
#endif
}
RgaFrameConverter::RgaFrameConverter(bool direct_dmabuf)
    : impl_(std::make_unique<Impl>()) {
    impl_->direct = direct_dmabuf;
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
    const int src_stride = impl_->direct ? static_cast<int>(p.stride)
                                         : (static_cast<int>(w) + 15) & ~15;
    const int dst_stride = (ow + 15) & ~15;
    auto& source = impl_->source;
    auto& destination = impl_->destination;
    rga_buffer_handle_t source_handle = 0;
    if (impl_->direct)
        source_handle = impl_->direct_source(f);
    else
        source.resize(static_cast<size_t>(src_stride) * h * 3 / 2);
    destination.resize(static_cast<size_t>(dst_stride) * oh * 3);
    if (!impl_->direct) {
        for (unsigned row = 0; row < h; ++row)
            std::memcpy(source.bytes.data() + static_cast<size_t>(row) * src_stride,
                        y + static_cast<size_t>(row) * p.stride,
                        w);
        for (unsigned row = 0; row < h / 2; ++row)
            std::memcpy(source.bytes.data() + static_cast<size_t>(src_stride) * h +
                            static_cast<size_t>(row) * src_stride,
                        uv + static_cast<size_t>(row) * uvstride,
                        w);
        source_handle = source.handle;
    }
    auto src =
        wrapbuffer_handle(source_handle,
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
    // Synchronous completion is required before reusing buffers or releasing the
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
