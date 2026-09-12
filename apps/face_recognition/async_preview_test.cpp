#include "async_preview.hpp"
#include <condition_variable>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <thread>
using namespace rtctrl::face;
void require(bool value) {
    if (!value)
        throw std::runtime_error("async preview assertion");
}
template <class F> void rejects(F f) {
    bool failed = false;
    try {
        f();
    } catch (const std::runtime_error&) {
        failed = true;
    }
    require(failed);
}
cv::Mat frame(int id) {
    return cv::Mat(2, 2, CV_8UC3, cv::Scalar(id, 0, 0));
}
int main() {
    try {
        std::mutex mutex;
        std::condition_variable changed;
        bool entered = false, allow = false;
        int count = 0;
        std::vector<int> ids;
        std::vector<std::string> statuses;
        {
            AsyncPreview preview(
                [&](const cv::Mat& image) {
                    std::unique_lock<std::mutex> lock(mutex);
                    if (!entered) {
                        entered = true;
                        changed.notify_all();
                        changed.wait(lock, [&] { return allow; });
                    }
                    return std::vector<unsigned char>{image.at<cv::Vec3b>(0, 0)[0]};
                },
                [&](std::vector<unsigned char> jpeg, std::string json) {
                    std::lock_guard<std::mutex> lock(mutex);
                    ids.push_back(jpeg[0]);
                    statuses.push_back(json);
                    ++count;
                    changed.notify_all();
                },
                "mock");
            preview.submit(frame(1), "{\"frame\":1}", PreviewClock::now());
            {
                std::unique_lock<std::mutex> lock(mutex);
                changed.wait(lock, [&] { return entered; });
            }
            for (int id = 2; id <= 20; ++id)
                preview.submit(frame(id),
                               "{\"frame\":" + std::to_string(id) + "}",
                               PreviewClock::now());
            {
                std::lock_guard<std::mutex> lock(mutex);
                allow = true;
            }
            changed.notify_all();
            {
                std::unique_lock<std::mutex> lock(mutex);
                changed.wait(lock, [&] { return count == 2; });
            }
            preview.finish();
            preview.check();
            rejects([&] { preview.submit(frame(2), "{}", PreviewClock::now()); });
        }
        require(ids == std::vector<int>({1, 20}));
        require(statuses[0].find("\"frame\":1,") != std::string::npos);
        require(statuses[1].find("\"frame\":20,") != std::string::npos);
        require(statuses[1].find("\"encode_overwrites\":18") != std::string::npos);
        require(statuses[1].find("\"published\":2") != std::string::npos);
        require(statuses[1].find("\"publish_fps\":") != std::string::npos);
        // A failing worker must propagate its error and permanently reject new work.
        entered = false;
        allow = false;
        {
            AsyncPreview broken(
                [&](const cv::Mat&) -> std::vector<unsigned char> {
                    std::unique_lock<std::mutex> lock(mutex);
                    entered = true;
                    changed.notify_all();
                    changed.wait(lock, [&] { return allow; });
                    throw std::runtime_error("encode failure");
                },
                [](std::vector<unsigned char>, std::string) {
                    throw std::runtime_error("must not publish");
                },
                "mock");
            broken.submit(frame(1), "{}", PreviewClock::now());
            {
                std::unique_lock<std::mutex> lock(mutex);
                changed.wait(lock, [&] { return entered; });
                allow = true;
            }
            changed.notify_all();
            rejects([&] { broken.finish(); });
            rejects([&] { broken.check(); });
            rejects([&] { broken.submit(frame(2), "{}", PreviewClock::now()); });
        }
        // Empty-idle destruction joins without requiring any frame or notification.
        {
            AsyncPreview idle(
                [](const cv::Mat&) { return std::vector<unsigned char>{1}; },
                [](std::vector<unsigned char>, std::string) {},
                "mock");
        }
        PreviewPublisher synchronous(
            [](const cv::Mat&) { return std::vector<unsigned char>{1}; },
            [](std::vector<unsigned char>, std::string) {},
            "mock");
        auto status = synchronous.publish(frame(1), "{}", PreviewClock::now());
        require(status.find("{\"encode_ms\":") == 0);
        rejects([&] { synchronous.publish(frame(1), "bad", PreviewClock::now()); });
        std::cout << "async preview tests passed\n";
    } catch (const std::exception& e) {
        std::cerr << e.what() << "\n";
        return 1;
    }
}
