#include "video_frame.hpp"
#include <iostream>
#include <stdexcept>
#include <vector>
using namespace rtctrl::face;
void check(bool b) {
    if (!b)
        throw std::runtime_error("video conversion assertion");
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
        std::cout << "video frame tests passed\n";
    } catch (const std::exception& e) {
        std::cerr << e.what() << "\n";
        return 1;
    }
}
