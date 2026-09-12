#include "detector_resize.hpp"
#include <algorithm>
#include <cmath>
#include <opencv2/core/version.hpp>
#include <opencv2/imgproc.hpp>
#include <stdexcept>
#include <string>
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
} // namespace
cv::Mat scalar_letterbox(const cv::Mat& source, int width, int height) {
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
        for (int x = 0; x < 320; ++x)
            for (int c = 0; c < 3; ++c) {
                const int index = (3 * x + 1) * 3 + c;
                destination[x * 3 + c] = static_cast<unsigned char>(
                    (((a[index] * b0) >> 9) + ((b[index] * b1) >> 9) + 2) >> 2);
            }
    }
    return output;
}
} // namespace rtctrl::face
