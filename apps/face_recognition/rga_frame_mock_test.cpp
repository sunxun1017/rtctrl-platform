#include "rga_frame.hpp"
#include <im2d.h>
#include <iostream>
#include <map>
#include <stdexcept>
#include <vector>
static std::map<rga_buffer_handle_t, void*> memory;
static unsigned serial = 0;
static bool fail = false;
static int fail_import_after = -1;
static int expected_format = RK_FORMAT_YCbCr_420_SP;
static int expected_mode = IM_YUV_TO_RGB_BT601_FULL;
rga_buffer_handle_t importbuffer_virtualaddr(void* p, int) {
    if (fail_import_after == 0)
        return 0;
    if (fail_import_after > 0)
        --fail_import_after;
    memory[++serial] = p;
    return serial;
}
IM_STATUS releasebuffer_handle(rga_buffer_handle_t h) {
    memory.erase(h);
    return IM_STATUS_SUCCESS;
}
rga_buffer_t wrapbuffer_handle(
    rga_buffer_handle_t h, int w, int height, int format, int ws, int hs) {
    rga_buffer_t b{};
    b.handle = h;
    b.width = w;
    b.height = height;
    b.format = format;
    b.wstride = ws;
    b.hstride = hs;
    return b;
}
const char* imStrError_t(IM_STATUS) {
    return "mock failure";
}
IM_STATUS imresize(rga_buffer_t src,
                   rga_buffer_t dst,
                   double,
                   double,
                   int interpolation,
                   int sync,
                   int*) {
    if (src.format != expected_format || dst.color_space_mode != expected_mode)
        throw std::runtime_error("format/matrix mismatch");
    if (fail)
        return IM_STATUS_FAILED;
    if (sync != 1 || interpolation != IM_INTERP_DEFAULT)
        throw std::runtime_error("sync/interpolation");
    auto* s = static_cast<unsigned char*>(memory.at(src.handle));
    auto* d = static_cast<unsigned char*>(memory.at(dst.handle));
    for (int row = 0; row < dst.height; ++row)
        for (int col = 0; col < dst.width; ++col) {
            auto off = row * dst.wstride * 3 + col * 3;
            d[off] = s[row * src.wstride + col];
            d[off + 1] = s[src.wstride * src.hstride];
            d[off + 2] = s[src.wstride * src.hstride + 1];
        }
    return IM_STATUS_SUCCESS;
}
void check(bool b) {
    if (!b)
        throw std::runtime_error("assert");
}
template <class F> void rejects(F f) {
    bool failed = false;
    try {
        f();
    } catch (...) {
        failed = true;
    }
    check(failed);
}
int main() {
    try {
        {
            rtctrl::face::RgaFrameConverter c;
            rtctrl_camera_frame f{};
            rejects([&] { c.convert(f, 16); });
            std::vector<unsigned char> y(24 * 4, 23), uv(28 * 2, 99);
            f.format = {18,
                        4,
                        RTCTRL_PIXEL_NV12,
                        0,
                        2,
                        0,
                        RTCTRL_RANGE_FULL,
                        0,
                        RTCTRL_YCBCR_BT601};
            f.planes[0].data = y.data();
            f.planes[0].stride = 24;
            f.planes[0].size = y.size();
            f.planes[1].data = uv.data();
            f.planes[1].stride = 28;
            f.planes[1].size = uv.size();
            uv[1] = 77;
            auto first = c.convert(f, 18);
            check(first.at<cv::Vec3b>(3, 17) == cv::Vec3b(23, 99, 77));
            auto keep = first.clone();
            unsigned imports = serial;
            y[0] = 45;
            auto second = c.convert(f, 18);
            check(serial == imports &&
                  first.at<cv::Vec3b>(0, 0) == keep.at<cv::Vec3b>(0, 0) &&
                  second.at<cv::Vec3b>(0, 0)[0] == 45);
            f.planes[1].size = 1;
            rejects([&] { c.convert(f, 18); });
            f.planes[1].size = uv.size();
            f.planes[0].allocation_size = 90;
            f.planes[0].data_offset = 30;
            rejects([&] { c.convert(f, 18); });
            f.planes[0].allocation_size = 0;
            f.format.pixel_format = RTCTRL_PIXEL_NV21;
            expected_format = RK_FORMAT_YCrCb_420_SP;
            c.convert(f, 18);
            f.format.ycbcr_encoding = 0;
            rejects([&] { c.convert(f, 18); });
            expected_mode = IM_YUV_TO_RGB_BT709_LIMIT;
            c.convert(f, 18, {RTCTRL_YCBCR_BT709, RTCTRL_RANGE_LIMITED});
            expected_mode = IM_YUV_TO_RGB_BT601_FULL;
            fail = true;
            rejects(
                [&] { c.convert(f, 18, {RTCTRL_YCBCR_BT601, RTCTRL_RANGE_FULL}); });
        }
        check(memory.empty());
        fail = false;
        expected_format = RK_FORMAT_YCbCr_420_SP;
        // Failure on destination import must also release the earlier source import.
        {
            rtctrl::face::RgaFrameConverter c;
            std::vector<unsigned char> packed(24 * 6, 128);
            rtctrl_camera_frame f{};
            f.format = {18,
                        4,
                        RTCTRL_PIXEL_NV12,
                        0,
                        1,
                        0,
                        RTCTRL_RANGE_FULL,
                        0,
                        RTCTRL_YCBCR_BT601};
            f.planes[0].data = packed.data();
            f.planes[0].size = packed.size();
            f.planes[0].stride = 24;
            fail_import_after = 1;
            rejects([&] { c.convert(f, 18); });
            check(memory.size() == 1);
            fail_import_after = -1;
            auto recovered = c.convert(f, 18);
            check(recovered.rows == 4 && recovered.cols == 18);
            // Dimension changes replace imports; the previous result remains
            // independent.
            auto retained = recovered.clone();
            f.format.width = 16;
            auto resized = c.convert(f, 16);
            check(memory.size() == 2 &&
                  recovered.at<cv::Vec3b>(0, 0) == retained.at<cv::Vec3b>(0, 0));
        }
        check(memory.empty());
        std::cout << "RGA converter ownership/validation tests passed\n";
    } catch (const std::exception& e) {
        std::cerr << e.what() << "\n";
        return 1;
    }
}
