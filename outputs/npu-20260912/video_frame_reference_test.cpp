#include "video_frame.hpp"
#include <iostream>
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <vector>
using namespace rtctrl::face;
void check(bool b) {
    if (!b)
        throw std::runtime_error("video conversion assertion");
}
// Independent scalar reference retained from the pre-LUT conversion, including
// operation ordering and nearest-neighbor coordinate mapping.
cv::Vec3b scalar_yuv(unsigned yy, unsigned uu, unsigned vv, unsigned m, unsigned r) {
    float kr = m == RTCTRL_YCBCR_BT709 ? 0.2126f : 0.299f;
    float kb = m == RTCTRL_YCBCR_BT709 ? 0.0722f : 0.114f;
    float kg = 1 - kr - kb;
    float y = yy, u = static_cast<float>(uu) - 128, v = static_cast<float>(vv) - 128;
    if (r == RTCTRL_RANGE_LIMITED) {
        y = (y - 16) * (255.0f / 219);
        u *= 255.0f / 224;
        v *= 255.0f / 224;
    }
    auto clip = [](float x) { return static_cast<unsigned char>(std::clamp(x + 0.5f, 0.0f, 255.0f)); };
    return {clip(y + 2 * (1 - kb) * u),
            clip(y - 2 * kb * (1 - kb) / kg * u - 2 * kr * (1 - kr) / kg * v),
            clip(y + 2 * (1 - kr) * v)};
}
void reference_test() {
    // Padding, independent chroma stride, resize and cache reconfiguration.
    constexpr unsigned w = 514, h = 34, ys = 520, us = 522;
    std::vector<unsigned char> y(ys * h, 173), uv(us * h / 2, 219);
    rtctrl_camera_frame f{};
    f.format.width = w; f.format.height = h; f.format.plane_count = 2;
    f.planes[0].data = y.data(); f.planes[0].size = y.size(); f.planes[0].stride = ys;
    f.planes[1].data = uv.data(); f.planes[1].size = uv.size(); f.planes[1].stride = us;
    for (unsigned matrix : {RTCTRL_YCBCR_BT601, RTCTRL_YCBCR_BT709})
        for (unsigned range : {RTCTRL_RANGE_FULL, RTCTRL_RANGE_LIMITED})
            for (unsigned fmt : {RTCTRL_PIXEL_NV12, RTCTRL_PIXEL_NV21}) {
                f.format.ycbcr_encoding = matrix; f.format.quantization = range; f.format.pixel_format = fmt;
                for (unsigned yy = 0; yy < 256; ++yy) {
                    std::fill(y.begin(), y.end(), yy);
                    for (unsigned row = 0; row < h / 2; ++row)
                        for (unsigned col = 0; col < w; col += 2) {
                            uv[row * us + col] = static_cast<unsigned char>(col / 2);
                            uv[row * us + col + 1] = static_cast<unsigned char>(std::min(row * 16, 255u));
                        }
                    for (int width : {514, 237}) {
                        const auto actual = video_frame_bgr(f, width);
                        for (int row = 0; row < actual.rows; ++row)
                            for (int col = 0; col < actual.cols; ++col) {
                                const auto sy = static_cast<size_t>(row) * h / actual.rows;
                                const auto sx = static_cast<size_t>(col) * w / actual.cols;
                                const auto off = sy / 2 * us + sx / 2 * 2;
                                const auto want = scalar_yuv(yy, uv[off + (fmt == RTCTRL_PIXEL_NV21)],
                                    uv[off + (fmt == RTCTRL_PIXEL_NV12)], matrix, range);
                                const auto got = actual.at<cv::Vec3b>(row,col);
                                if (got != want) {
                                    std::cerr << "reference mismatch matrix=" << matrix << " range=" << range
                                              << " fmt=" << fmt << " width=" << width << " row=" << row
                                              << " col=" << col << " Y=" << yy << " uv=" << unsigned(uv[off])
                                              << "," << unsigned(uv[off+1]) << " got=" << got << " want=" << want << "\n";
                                }
                                check(got == want);
                            }
                    }
                }
            }
    auto first = video_frame_bgr(f, 514);
    auto saved = first.clone();
    std::fill(y.begin(), y.end(), 0);
    auto second = video_frame_bgr(f, 237);
    check(first.data != second.data && cv::norm(first, saved, cv::NORM_INF) == 0);
}
int main() {
    try {
        rtctrl_camera_frame f{};
        f.format = {2,
                    2,
                    RTCTRL_PIXEL_NV12,
                    0,
                    1,
                    0,
                    RTCTRL_RANGE_FULL,
                    0,
                    RTCTRL_YCBCR_BT601};
        std::vector<unsigned char> data = {
            0, 255, 99, 99, 128, 64, 99, 99, 128, 128, 99, 99};
        f.planes[0].data = data.data();
        f.planes[0].size = data.size();
        f.planes[0].stride = 4;
        auto b = video_frame_bgr(f, 2);
        check(b.at<cv::Vec3b>(0, 0) == cv::Vec3b(0, 0, 0));
        check(b.at<cv::Vec3b>(0, 1) == cv::Vec3b(255, 255, 255));
        check(b.at<cv::Vec3b>(1, 0) == cv::Vec3b(128, 128, 128));
        data[0] = 16;
        data[1] = 235;
        f.format.quantization = RTCTRL_RANGE_LIMITED;
        b = video_frame_bgr(f, 2);
        check(b.at<cv::Vec3b>(0, 0) == cv::Vec3b(0, 0, 0));
        check(b.at<cv::Vec3b>(0, 1) == cv::Vec3b(255, 255, 255));
        f.format.quantization = RTCTRL_RANGE_FULL;
        data[0] = 76;
        data[8] = 85;
        data[9] = 255;
        b = video_frame_bgr(f, 2);
        auto red = b.at<cv::Vec3b>(0, 0);
        check(red[2] > 250 && red[1] < 3 && red[0] < 3);
        f.format.plane_count = 2;
        f.planes[1].data = data.data() + 8;
        f.planes[1].size = 2;
        f.planes[1].stride = 2;
        f.planes[0].size = 6;
        check(video_frame_bgr(f, 2).at<cv::Vec3b>(0, 0) == red);
        f.format.pixel_format = RTCTRL_PIXEL_NV21;
        std::swap(data[8], data[9]);
        check(video_frame_bgr(f, 2).at<cv::Vec3b>(0, 0) == red);
        f.planes[1].size = 1;
        bool failed = false;
        try {
            video_frame_bgr(f, 2);
        } catch (...) {
            failed = true;
        }
        check(failed);
        f.planes[1].size = 2;
        f.format.ycbcr_encoding = RTCTRL_YCBCR_UNKNOWN;
        failed = false;
        try {
            video_frame_bgr(f, 2);
        } catch (...) {
            failed = true;
        }
        check(failed);
        check(video_frame_bgr(f, 2, {RTCTRL_YCBCR_BT601, RTCTRL_RANGE_FULL})
                  .at<cv::Vec3b>(0, 0) == red);
        std::vector<unsigned char> rgb = {
            1, 2, 3, 4, 5, 6, 88, 88, 7, 8, 9, 10, 11, 12};
        f.format = {2, 2, RTCTRL_PIXEL_RGB24, 0, 1, 0, 0, 0, 0};
        f.planes[0].data = rgb.data();
        f.planes[0].size = rgb.size();
        f.planes[0].stride = 8;
        b = video_frame_bgr(f, 2);
        check(b.at<cv::Vec3b>(1, 1) == cv::Vec3b(12, 11, 10));
        rgb[0] = 100;
        check(b.at<cv::Vec3b>(0, 0) == cv::Vec3b(3, 2, 1));
        reference_test();
        std::cout << "video frame tests passed\n";
    } catch (const std::exception& e) {
        std::cerr << e.what() << "\n";
        return 1;
    }
}
