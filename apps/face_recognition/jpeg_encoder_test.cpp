#include "jpeg_encoder.hpp"
#include <iostream>
#include <opencv2/imgcodecs.hpp>
#include <stdexcept>
using rtctrl::face::JpegEncoder;
void check(bool b) {
    if (!b)
        throw std::runtime_error("JPEG encoder assertion");
}
template <class F> void rejects(F f) {
    bool failed = false;
    try {
        f();
    } catch (const std::exception&) {
        failed = true;
    }
    check(failed);
}
int main(int argc, char** argv) {
    try {
        rejects([] { JpegEncoder bad("unknown"); });
        rejects(
            [] { JpegEncoder bad("turbojpeg", "/nonexistent/rtctrl-no-jpeg.so"); });
        JpegEncoder cv;
        rejects([&] { cv.encode({}, 75); });
        rejects([&] { cv.encode(cv::Mat(2, 2, CV_8UC1), 75); });
        rejects([&] { cv.encode(cv::Mat(2, 2, CV_8UC3), 0); });
        rejects([&] { cv.encode(cv::Mat(1, 8193, CV_8UC3), 75); });
        cv::Mat storage(18, 26, CV_8UC3, cv::Scalar(15, 60, 90));
        auto roi = storage(cv::Rect(2, 2, 20, 12));
        check(!roi.isContinuous());
        auto original = cv.encode(roi, 75);
        check(cv::imdecode(original, cv::IMREAD_COLOR).size() == roi.size());
        auto saved = original;
        roi.setTo(cv::Scalar(90, 30, 15));
        auto next = cv.encode(roi, 75);
        check(original == saved && original != next);
        if (argc > 1) {
            check(JpegEncoder::turbojpeg_compiled());
            JpegEncoder turbo("turbojpeg", argv[1]);
            auto first = turbo.encode(roi, 75);
            auto copy = first;
            check(first.size() == 6 && first[0] == 90 && first[1] == 30 &&
                  first[2] == 15);
            roi.setTo(cv::Scalar(1, 2, 3));
            auto second = turbo.encode(roi, 75);
            check(first == copy && second[0] == 1 && first.data() != second.data());
            auto changed =
                turbo.encode(cv::Mat(4, 6, CV_8UC3, cv::Scalar(7, 8, 9)), 95);
            check(changed[0] == 7 && changed[3] == 6 && changed[4] == 4 &&
                  changed[5] == 95);
            rejects([&] { turbo.encode(roi, 13); });
            rejects([&] { turbo.encode(roi, 14); });
        } else if (!JpegEncoder::turbojpeg_compiled()) {
            rejects([] { JpegEncoder absent("turbojpeg"); });
        }
        std::cout << "JPEG encoder tests passed\n";
    } catch (const std::exception& e) {
        std::cerr << e.what() << "\n";
        return 1;
    }
}
