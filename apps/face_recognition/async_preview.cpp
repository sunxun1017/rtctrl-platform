#include "async_preview.hpp"
#include "jpeg_encoder.hpp"
#include "preview_server.hpp"
#include <algorithm>
#include <condition_variable>
#include <exception>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <thread>
namespace rtctrl::face {
namespace {
PreviewEncode encoder(const std::string& name, int quality) {
    auto implementation = std::make_shared<JpegEncoder>(name);
    return [implementation, quality](const cv::Mat& image) {
        return implementation->encode(image, quality);
    };
}
PreviewPublish sink(PreviewServer& server) {
    return [&server](std::vector<unsigned char> jpeg, std::string json) {
        server.publish(std::move(jpeg), std::move(json));
    };
}
double elapsed(PreviewClock::time_point a, PreviewClock::time_point b) {
    return std::chrono::duration<double, std::milli>(b - a).count();
}
std::string quoted(const std::string& value) {
    std::string out = "\"";
    for (unsigned char c : value) {
        if (c == '"' || c == '\\')
            out += '\\';
        if (c < 32)
            throw std::runtime_error("invalid preview encoder name");
        out += c;
    }
    return out + '"';
}
} // namespace
PreviewPublisher::PreviewPublisher(PreviewServer& server,
                                   const std::string& name,
                                   int quality)
    : PreviewPublisher(encoder(name, quality), sink(server), name) {}
PreviewPublisher::PreviewPublisher(PreviewEncode encode,
                                   PreviewPublish publish,
                                   std::string name)
    : encode_(std::move(encode))
    , publish_(std::move(publish))
    , encoder_(std::move(name)) {
    if (!encode_ || !publish_)
        throw std::runtime_error("missing preview callback");
}
std::string PreviewPublisher::publish(const cv::Mat& image,
                                      std::string json,
                                      PreviewClock::time_point dequeued,
                                      uint64_t overwrites) {
    const auto end = json.find_last_not_of(" \t\r\n");
    const auto begin = json.find_first_not_of(" \t\r\n");
    if (begin == std::string::npos || json[begin] != '{' || end == begin ||
        json[end] != '}')
        throw std::runtime_error("preview status must be a JSON object");
    const auto encode_begin = PreviewClock::now();
    auto jpeg = encode_(image);
    const auto ready = PreviewClock::now();
    if (jpeg.empty())
        throw std::runtime_error("preview encoder returned no JPEG");
    // Intervals are measured at completed-JPEG publication, never inference.
    const double fps =
        published_ ? 1000.0 / std::max(0.001, elapsed(previous_, ready)) : 0;
    json.resize(end);
    const bool empty =
        json.find_first_not_of(" \t\r\n", begin + 1) == std::string::npos;
    std::ostringstream status;
    status << json << (empty ? "" : ",")
           << "\"encode_ms\":" << elapsed(encode_begin, ready)
           << ",\"jpeg_encoder\":" << quoted(encoder_)
           << ",\"published\":" << published_ + 1
           << ",\"encode_overwrites\":" << overwrites << ",\"publish_fps\":" << fps
           << ",\"ready_age_ms\":" << elapsed(dequeued, ready) << '}';
    auto result = status.str();
    publish_(std::move(jpeg), result);
    ++published_;
    previous_ = ready;
    return result;
}
struct AsyncPreview::Impl {
    struct Job {
        cv::Mat image;
        std::string json;
        PreviewClock::time_point dequeued;
    };
    PreviewPublisher publisher;
    mutable std::mutex mutex;
    std::condition_variable changed;
    std::optional<Job> pending;
    uint64_t overwrites = 0;
    bool stopping = false;
    std::exception_ptr error;
    std::thread worker;
    Impl(PreviewEncode encode, PreviewPublish publish, std::string name)
        : publisher(std::move(encode), std::move(publish), std::move(name))
        , worker([this] { run(); }) {}
    ~Impl() {
        stop();
    }
    void stop() {
        {
            std::lock_guard<std::mutex> lock(mutex);
            stopping = true;
            pending.reset();
        }
        changed.notify_all();
        if (worker.joinable())
            worker.join();
    }
    void run() noexcept {
        try {
            for (;;) {
                Job job;
                uint64_t skipped;
                {
                    std::unique_lock<std::mutex> lock(mutex);
                    changed.wait(lock,
                                 [this] { return stopping || pending.has_value(); });
                    if (stopping)
                        return;
                    job = std::move(*pending);
                    pending.reset();
                    skipped = overwrites;
                }
                publisher.publish(
                    job.image, std::move(job.json), job.dequeued, skipped);
            }
        } catch (...) {
            std::lock_guard<std::mutex> lock(mutex);
            error = std::current_exception();
            stopping = true;
            pending.reset();
        }
    }
};
AsyncPreview::AsyncPreview(PreviewServer& server,
                           const std::string& name,
                           int quality)
    : AsyncPreview(encoder(name, quality), sink(server), name) {}
AsyncPreview::AsyncPreview(PreviewEncode encode,
                           PreviewPublish publish,
                           std::string name)
    : impl_(std::make_unique<Impl>(
          std::move(encode), std::move(publish), std::move(name))) {}
AsyncPreview::~AsyncPreview() = default;
void AsyncPreview::submit(cv::Mat image,
                          std::string json,
                          PreviewClock::time_point dequeued) {
    if (image.empty())
        throw std::runtime_error("empty preview frame");
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->error)
        std::rethrow_exception(impl_->error);
    if (impl_->stopping)
        throw std::runtime_error("preview worker stopped");
    if (impl_->pending)
        ++impl_->overwrites;
    impl_->pending = Impl::Job{std::move(image), std::move(json), dequeued};
    impl_->changed.notify_one();
}
void AsyncPreview::finish() {
    impl_->stop();
    check();
}
void AsyncPreview::check() const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->error)
        std::rethrow_exception(impl_->error);
}
} // namespace rtctrl::face
