#pragma once
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <opencv2/core.hpp>
#include <string>
#include <vector>
namespace rtctrl::face {
class PreviewServer;
using PreviewClock = std::chrono::steady_clock;
// Callbacks permit deterministic consumer tests without hardware or HTTP.
using PreviewEncode = std::function<std::vector<unsigned char>(const cv::Mat&)>;
using PreviewPublish = std::function<void(std::vector<unsigned char>, std::string)>;
class PreviewPublisher {
  public:
    PreviewPublisher(PreviewServer& server, const std::string& encoder, int quality);
    PreviewPublisher(PreviewEncode encode,
                     PreviewPublish publish,
                     std::string encoder);
    std::string publish(const cv::Mat& image,
                        std::string json,
                        PreviewClock::time_point dequeued,
                        uint64_t overwrites = 0);

  private:
    PreviewEncode encode_;
    PreviewPublish publish_;
    std::string encoder_;
    uint64_t published_ = 0;
    PreviewClock::time_point previous_{};
};
class AsyncPreview {
  public:
    AsyncPreview(PreviewServer& server, const std::string& encoder, int quality);
    AsyncPreview(PreviewEncode encode, PreviewPublish publish, std::string encoder);
    ~AsyncPreview();
    AsyncPreview(const AsyncPreview&) = delete;
    AsyncPreview& operator=(const AsyncPreview&) = delete;
    // Transfers owned pixels. Neither caller nor any cv::Mat alias may mutate
    // them afterwards. Queue capacity is one, plus the currently encoding job.
    void submit(cv::Mat image, std::string json, PreviewClock::time_point dequeued);
    void check() const;
    // Stop, discard pending work, join an in-flight publish, and report errors.
    void finish();

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace rtctrl::face
