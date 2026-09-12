#include "detector_resize.hpp"
#include <algorithm>
#include <cmath>
#include <opencv2/core/version.hpp>
#include <opencv2/imgproc.hpp>
#include <stdexcept>
#include <string>
#if defined(__aarch64__) && defined(__ARM_NEON)
#include <arm_neon.h>
#endif
namespace rtctrl::face {
namespace {
bool verified_build() {
#if CV_VERSION_MAJOR == 3 && CV_VERSION_MINOR == 4 && CV_VERSION_REVISION == 5
    static const bool verified =
        cv::getBuildInformation().find("General configuration for OpenCV 3.4.5 ") !=
        std::string::npos;
    return verified;
#else
    return false;
#endif
}
#if defined(__aarch64__) && defined(__ARM_NEON)
// Gather every third RGB pixel from 48 source pixels. Loading from 3*x rather
// than 3*x+1 keeps the final vector entirely inside the 960-pixel source row.
uint8x16x3_t selected(const unsigned char* row) {
    const auto a = vld3q_u8(row);
    const auto b = vld3q_u8(row + 48);
    const auto c = vld3q_u8(row + 96);
    const uint8_t positions[16] = {
        1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34, 37, 40, 43, 46};
    const auto index = vld1q_u8(positions);
    uint8x16x3_t result;
    for (int channel = 0; channel < 3; ++channel) {
        uint8x16x3_t table;
        table.val[0] = a.val[channel];
        table.val[1] = b.val[channel];
        table.val[2] = c.val[channel];
        result.val[channel] = vqtbl3q_u8(table, index);
    }
    return result;
}
uint16x8_t vertical_half(uint16x8_t a, uint16x8_t b, uint16_t b0, uint16_t b1) {
    // Products need 19 bits. Truncate each product independently, matching
    // OpenCV 3.4.5 before adding the final rounding bias.
    const auto al = vshrn_n_u32(vmull_n_u16(vget_low_u16(a), b0), 9);
    const auto ah = vshrn_n_u32(vmull_n_u16(vget_high_u16(a), b0), 9);
    const auto bl = vshrn_n_u32(vmull_n_u16(vget_low_u16(b), b1), 9);
    const auto bh = vshrn_n_u32(vmull_n_u16(vget_high_u16(b), b1), 9);
    return vaddq_u16(vaddq_u16(vcombine_u16(al, ah), vcombine_u16(bl, bh)),
                     vdupq_n_u16(2));
}
uint8x16_t vertical(uint8x16_t a, uint8x16_t b, uint16_t b0, uint16_t b1) {
    return vcombine_u8(
        vshrn_n_u16(vertical_half(
                        vmovl_u8(vget_low_u8(a)), vmovl_u8(vget_low_u8(b)), b0, b1),
                    2),
        vshrn_n_u16(
            vertical_half(
                vmovl_u8(vget_high_u8(a)), vmovl_u8(vget_high_u8(b)), b0, b1),
            2));
}
#endif
} // namespace
cv::Mat prefetch576(const cv::Mat& source, int width, int height) {
    if (source.empty() || source.type() != CV_8UC3 || width < 1 || width > 320 ||
        height < 1 || height > 320)
        throw std::invalid_argument("Invalid detector letterbox input");
    cv::Mat output(320, 320, CV_8UC3, cv::Scalar(0, 0, 0));
    const int top = (320 - height) / 2;
    const bool eligible =
        verified_build() && source.cols == 960 && source.rows <= 960 &&
        width == 320 &&
        height == std::max(1, int(std::round(source.rows * (320.f / source.cols))));
    if (!eligible) {
        cv::Mat resized;
        cv::resize(source, resized, {width, height}, 0, 0, cv::INTER_LINEAR);
        resized.copyTo(output(cv::Rect((320 - width) / 2, top, width, height)));
        return output;
    }
    // OpenCV 3.4.5 INTER_LINEAR uses 11-bit coefficients. At scale_x=3
    // x maps exactly to 3*x+1, making the horizontal sum pixel*2048.
    // Keep the vertical stage's separate truncations before the final rounding.
    const double scale_y = 1.0 / (double(height) / source.rows);
    for (int y = 0; y < height; ++y) {
        float fy = float((y + 0.5) * scale_y - 0.5);
        const int sy = cvFloor(fy);
        fy -= sy;
        const int b0 = cv::saturate_cast<short>((1.f - fy) * 2048);
        const int b1 = cv::saturate_cast<short>(fy * 2048);
        const auto* a =
            source.ptr<unsigned char>(std::clamp(sy, 0, source.rows - 1));
        const auto* b =
            source.ptr<unsigned char>(std::clamp(sy + 1, 0, source.rows - 1));
        auto* destination = output.ptr<unsigned char>(y + top);
#if defined(__aarch64__) && defined(__ARM_NEON)
        for (int x = 0; x < 320; x += 16) {
            // Explicitly bound even the prefetch pointer to the active row.
            const int ahead = x * 9 + 576;
            if (ahead + 128 < 960 * 3) {
                __builtin_prefetch(a + ahead, 0, 3);
                __builtin_prefetch(a + ahead + 64, 0, 3);
                __builtin_prefetch(a + ahead + 128, 0, 3);
                __builtin_prefetch(b + ahead, 0, 3);
                __builtin_prefetch(b + ahead + 64, 0, 3);
                __builtin_prefetch(b + ahead + 128, 0, 3);
            }
            const auto av = selected(a + x * 9);
            const auto bv = selected(b + x * 9);
            uint8x16x3_t result;
            for (int c = 0; c < 3; ++c)
                result.val[c] = vertical(av.val[c], bv.val[c], b0, b1);
            vst3q_u8(destination + x * 3, result);
        }
#else
        for (int x = 0; x < 320; ++x)
            for (int c = 0; c < 3; ++c) {
                const int index = (3 * x + 1) * 3 + c;
                destination[x * 3 + c] = static_cast<unsigned char>(
                    (((a[index] * b0) >> 9) + ((b[index] * b1) >> 9) + 2) >> 2);
            }
#endif
    }
    return output;
}
} // namespace rtctrl::face
