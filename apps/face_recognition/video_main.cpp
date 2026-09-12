#include "digest.hpp"
#include "pipeline.hpp"
#include "preview_server.hpp"
#include "rtctrl/adapters/rknn/backend.hpp"
#include "rtctrl/adapters/v4l2/capture.h"
#include "video_frame.hpp"
#include "video_match.hpp"
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <csignal>
#include <cstring>
#include <iostream>
#include <map>
#include <mutex>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <sstream>
#include <stdexcept>
#include <thread>
namespace {
using Clock = std::chrono::steady_clock;
volatile std::sig_atomic_t interrupted = 0;
void interrupt(int) {
    interrupted = 1;
}
double millis(Clock::time_point a, Clock::time_point b) {
    return std::chrono::duration<double, std::milli>(b - a).count();
}
struct Options {
    std::string device, detector, recognizer, gallery, bind = "0.0.0.0", enrollment,
                                                       enrollment_image;
    int port = 8080, width = 960, quality = 75, duration = 0, frames = 0,
        max_faces = 8, enrollment_samples = 5;
    float threshold = 0, gap = 0;
    rtctrl::face::VideoColor color;
};
Options parse(int argc, char** argv) {
    std::map<std::string, std::string> args;
    for (int i = 1; i < argc; i += 2) {
        if (i + 1 >= argc || !args.emplace(argv[i], argv[i + 1]).second)
            throw std::runtime_error("missing/duplicate option value");
    }
    const std::string allowed =
        " --device --detector --recognizer --gallery --threshold --gap --bind "
        "--port --width --quality --duration --frames --max-faces --yuv-matrix "
        "--yuv-range --enroll-name --enroll-image --enroll-samples ";
    for (auto& a : args)
        if (allowed.find(" " + a.first + " ") == std::string::npos)
            throw std::runtime_error("unknown option: " + a.first);
    auto get = [&](const std::string& k, const std::string& d = "") {
        return args.count(k) ? args.at(k) : d;
    };
    auto number = [&](const std::string& k, double d, double lo, double hi) {
        if (!args.count(k))
            return d;
        size_t end = 0;
        double v = std::stod(args.at(k), &end);
        if (end != args.at(k).size() || !std::isfinite(v) || v < lo || v > hi)
            throw std::runtime_error("invalid " + k);
        return v;
    };
    auto integer = [&](const std::string& k, int d, int lo, int hi) {
        double v = number(k, d, lo, hi);
        if (std::floor(v) != v)
            throw std::runtime_error("integer required: " + k);
        return static_cast<int>(v);
    };
    Options o;
    o.device = get("--device");
    o.detector = get("--detector");
    o.recognizer = get("--recognizer");
    o.gallery = get("--gallery");
    o.bind = get("--bind", o.bind);
    if (o.device.empty() || o.detector.empty() || o.recognizer.empty() ||
        !args.count("--threshold"))
        throw std::runtime_error(
            "required: --device --detector --recognizer --threshold");
    o.threshold = static_cast<float>(number("--threshold", 0, -1, 1));
    o.gap = static_cast<float>(number("--gap", 0, 0, 2));
    o.port = integer("--port", 8080, 1, 65535);
    o.width = integer("--width", 960, 160, 4096);
    o.quality = integer("--quality", 75, 20, 95);
    o.duration = integer("--duration", 0, 0, 86400);
    o.frames = integer("--frames", 0, 0, 1000000);
    o.max_faces = integer("--max-faces", 8, 1, 32);
    o.enrollment_samples = integer("--enroll-samples", 5, 1, 20);
    auto matrix = get("--yuv-matrix", "auto"), range = get("--yuv-range", "auto");
    if (matrix == "bt601")
        o.color.matrix = RTCTRL_YCBCR_BT601;
    else if (matrix == "bt709")
        o.color.matrix = RTCTRL_YCBCR_BT709;
    else if (matrix != "auto")
        throw std::runtime_error("invalid --yuv-matrix");
    if (range == "full")
        o.color.range = RTCTRL_RANGE_FULL;
    else if (range == "limited")
        o.color.range = RTCTRL_RANGE_LIMITED;
    else if (range != "auto")
        throw std::runtime_error("invalid --yuv-range");
    o.enrollment = get("--enroll-name");
    o.enrollment_image = get("--enroll-image");
    if (!o.enrollment.empty() && (o.gallery.empty() || o.enrollment_image.empty()))
        throw std::runtime_error(
            "--enroll-name requires --gallery and --enroll-image (snapshot output)");
    if (o.enrollment.empty() && !o.enrollment_image.empty())
        throw std::runtime_error("--enroll-image requires --enroll-name");
    return o;
}
struct Latest {
    std::mutex mutex;
    std::condition_variable ready;
    cv::Mat image;
    uint32_t sequence = 0;
    Clock::time_point dequeued;
    uint64_t captured = 0, dropped = 0;
    bool available = false;
    std::string error;
    std::atomic<bool> stop{false};
};
void capture(Latest& latest, const Options& options) {
    rtctrl_camera* camera = nullptr;
    try {
        rtctrl_v4l2_config config{};
        config.device = options.device.c_str();
        config.buffer_count = 4;
        int rc = rtctrl_v4l2_open(&config, &camera);
        if (rc)
            throw std::runtime_error(std::string("camera open: ") +
                                     std::strerror(-rc));
        auto last = Clock::now();
        unsigned warmup = 30;
        while (!latest.stop.load()) {
            rtctrl_camera_frame frame{};
            rc = rtctrl_camera_acquire(camera, 100, &frame);
            if (rc == -EAGAIN || rc == -EINTR || rc == -ETIMEDOUT) {
                if (millis(last, Clock::now()) > 5000)
                    throw std::runtime_error(
                        "camera produced no frame for 5 seconds");
                continue;
            }
            if (rc)
                throw std::runtime_error(std::string("camera acquire: ") +
                                         std::strerror(-rc));
            auto dequeued = Clock::now();
            cv::Mat image;
            try {
                if (!frame.corrupt && !warmup)
                    image = rtctrl::face::video_frame_bgr(
                        frame, options.width, options.color);
            } catch (...) {
                rtctrl_camera_release(camera, frame.token);
                throw;
            }
            rc = rtctrl_camera_release(camera, frame.token);
            if (rc)
                throw std::runtime_error(std::string("camera release: ") +
                                         std::strerror(-rc));
            if (warmup) {
                --warmup;
                last = Clock::now();
                continue;
            }
            if (image.empty()) {
                if (millis(last, Clock::now()) > 5000)
                    throw std::runtime_error("camera returned only corrupt frames");
                continue;
            }
            last = Clock::now();
            {
                std::lock_guard<std::mutex> lock(latest.mutex);
                if (latest.available)
                    ++latest.dropped;
                latest.image = std::move(image);
                latest.sequence = frame.sequence;
                latest.dequeued = dequeued;
                latest.available = true;
                ++latest.captured;
            }
            latest.ready.notify_one();
        }
    } catch (const std::exception& e) {
        std::lock_guard<std::mutex> lock(latest.mutex);
        latest.error = e.what();
        latest.ready.notify_one();
    }
    int rc = rtctrl_camera_close(camera);
    if (rc) {
        std::lock_guard<std::mutex> lock(latest.mutex);
        if (latest.error.empty())
            latest.error = "camera close failed";
    }
}
struct CaptureWorker {
    Latest latest;
    std::thread thread;
    explicit CaptureWorker(const Options& o)
        : thread(capture, std::ref(latest), std::cref(o)) {}
    ~CaptureWorker() {
        latest.stop = true;
        if (thread.joinable())
            thread.join();
    }
};
} // namespace
int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--help") {
            std::cout
                << "rtctrl_face_video --device /dev/video31 --detector "
                   "detector.rknn --recognizer recognizer.rknn --threshold VALUE "
                   "[--gallery gallery.json] [--bind 0.0.0.0 --port 8080] [--width "
                   "960 --quality 75 --max-faces 8] [--yuv-matrix auto|bt601|bt709 "
                   "--yuv-range auto|full|limited] [--duration SECONDS --frames "
                   "COUNT] [--enroll-name NAME --enroll-image snapshot "
                   "--enroll-samples 5]\n";
            return 0;
        }
        auto options = parse(argc, argv);
        std::signal(SIGINT, interrupt);
        std::signal(SIGTERM, interrupt);
        cv::setNumThreads(1);
        rknn::RknnBackend detector(options.detector.c_str()),
            recognizer(options.recognizer.c_str());
        rtctrl::face::Gallery gallery;
        if (!options.gallery.empty())
            gallery = rtctrl::face::load_gallery(
                options.gallery,
                rtctrl::face::model_fingerprint(options.recognizer),
                !options.enrollment.empty());
        rtctrl::face::PreviewServer preview(
            options.bind, static_cast<unsigned short>(options.port));
        std::cerr << "Preview listening on " << options.bind << ":" << preview.port()
                  << "; threshold=" << options.threshold << " gap=" << options.gap
                  << " yuv_matrix_override=" << options.color.matrix
                  << " yuv_range_override=" << options.color.range << "\n";
        CaptureWorker worker(options);
        uint64_t processed = 0;
        bool enrolled = options.enrollment.empty();
        int enrollment_count = 0;
        auto last_enrollment = Clock::now() - std::chrono::seconds(2);
        auto started = Clock::now(), previous = started;
        while (!interrupted) {
            if (options.duration &&
                millis(started, Clock::now()) >= options.duration * 1000.0)
                break;
            cv::Mat image;
            uint32_t sequence;
            uint64_t dropped;
            Clock::time_point dequeued;
            {
                auto& latest = worker.latest;
                std::unique_lock<std::mutex> lock(latest.mutex);
                latest.ready.wait_for(lock, std::chrono::milliseconds(100), [&] {
                    return latest.available || !latest.error.empty();
                });
                if (!latest.error.empty())
                    throw std::runtime_error(latest.error);
                if (!latest.available)
                    continue;
                image = std::move(latest.image);
                sequence = latest.sequence;
                dequeued = latest.dequeued;
                dropped = latest.dropped;
                latest.available = false;
            }
            auto begin = Clock::now();
            auto faces = rtctrl::face::detect(
                detector,
                image,
                0.8f,
                enrolled ? options.max_faces : std::max(2, options.max_faces));
            auto detected = Clock::now();
            std::vector<rtctrl::face::Match> matches;
            matches.reserve(faces.size());
            for (auto& face : faces) {
                auto embedding = rtctrl::face::embed(recognizer, image, face);
                if (!enrolled && faces.size() == 1 &&
                    millis(last_enrollment, Clock::now()) >= 1000) {
                    if (gallery.dimension && gallery.dimension != embedding.size())
                        throw std::runtime_error("gallery dimension mismatch");
                    if (!cv::imwrite(options.enrollment_image + "." +
                                         std::to_string(enrollment_count + 1) +
                                         ".jpg",
                                     image))
                        throw std::runtime_error("cannot save enrollment image");
                    gallery.dimension = embedding.size();
                    gallery.samples.push_back({options.enrollment, embedding});
                    rtctrl::face::save_gallery(options.gallery, gallery);
                    last_enrollment = Clock::now();
                    ++enrollment_count;
                    enrolled = enrollment_count >= options.enrollment_samples;
                    std::cerr << "Enrolled " << options.enrollment << " sample "
                              << enrollment_count << "/"
                              << options.enrollment_samples << "\n";
                }
                matches.push_back(rtctrl::face::video_match(
                    gallery, embedding, options.threshold, options.gap));
            }
            auto recognized = Clock::now();
            ++processed;
            double fps = processed > 1
                             ? 1000.0 / std::max(0.001, millis(previous, recognized))
                             : 0;
            previous = recognized;
            std::ostringstream json;
            json << "{\"running\":true,\"frame\":" << sequence
                 << ",\"processed\":" << processed << ",\"dropped\":" << dropped
                 << ",\"fps\":" << fps
                 << ",\"detect_ms\":" << millis(begin, detected)
                 << ",\"recognize_ms\":" << millis(detected, recognized)
                 << ",\"processing_ms\":" << millis(begin, recognized)
                 << ",\"frame_age_ms\":" << millis(dequeued, recognized)
                 << ",\"width\":" << image.cols << ",\"height\":" << image.rows
                 << ",\"faces\":[";
            for (size_t i = 0; i < faces.size(); ++i) {
                const auto& f = faces[i];
                const auto& m = matches[i];
                if (i)
                    json << ',';
                json << "{\"name\":" << rtctrl::face::json_string(m.name)
                     << ",\"similarity\":" << m.similarity
                     << ",\"confidence\":" << f.confidence << ",\"box\":[" << f.box.x
                     << ',' << f.box.y << ',' << f.box.width << ',' << f.box.height
                     << "]}";
                cv::rectangle(image, f.box, cv::Scalar(40, 220, 80), 2);
                for (auto& p : f.landmarks)
                    cv::circle(image, p, 2, cv::Scalar(0, 80, 255), -1);
                std::ostringstream label;
                label << m.name;
                if (!gallery.samples.empty())
                    label << " " << static_cast<int>(m.similarity * 100) << "% sim";
                cv::putText(image,
                            label.str(),
                            cv::Point(static_cast<int>(f.box.x),
                                      std::max(18, static_cast<int>(f.box.y) - 6)),
                            cv::FONT_HERSHEY_SIMPLEX,
                            0.55,
                            cv::Scalar(40, 220, 80),
                            2);
            }
            json << "],\"note\":"
                 << rtctrl::face::json_string(
                        !enrolled ? "等待单人正脸，正在准备登记"
                        : options.gallery.empty()
                            ? "尚未加载人员库，当前仅检测并显示 unknown"
                            : "相似度不是准确率；当前阈值仍需用独立样本标定")
                 << "}";
            std::vector<unsigned char> jpeg;
            if (!cv::imencode(".jpg",
                              image,
                              jpeg,
                              {cv::IMWRITE_JPEG_QUALITY, options.quality}))
                throw std::runtime_error("JPEG encoding failed");
            preview.publish(std::move(jpeg), json.str());
            if (processed == 1 || processed % 30 == 0)
                std::cout << json.str() << std::endl;
            if (options.frames && processed >= static_cast<uint64_t>(options.frames))
                break;
        }
        if (!enrolled)
            throw std::runtime_error(
                "ended before a single face was available for enrollment");
        std::cerr << "Stopped after " << processed << " processed frames\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "face video: " << e.what() << "\n";
        return 1;
    }
}
