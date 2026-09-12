#include "pipeline.hpp"
#include "rtctrl/adapters/rknn/backend.hpp"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <vector>

static cv::Mat read_bgr(const char* path, int w, int h) {
    std::ifstream f(path, std::ios::binary | std::ios::ate);
    const auto bytes = static_cast<std::streamoff>(w) * h * 3;
    if (!f || f.tellg() != bytes) throw std::runtime_error("BGR file size mismatch");
    cv::Mat image(h, w, CV_8UC3);
    f.seekg(0);
    if (!f.read(reinterpret_cast<char*>(image.data), bytes))
        throw std::runtime_error("BGR read failed");
    return image;
}
static int dimension(const char* text) {
    std::size_t end = 0;
    int v = std::stoi(text, &end);
    if (text[end] || v < 1 || v > 8192) throw std::runtime_error("invalid dimension");
    return v;
}
static float overlap(const cv::Rect2f& a, const cv::Rect2f& b) {
    float intersection = (a & b).area();
    float total = a.area() + b.area() - intersection;
    return total > 0 ? intersection / total : 0;
}
static void box(const cv::Rect2f& r) {
    std::cout << '[' << r.x << ',' << r.y << ',' << r.width << ',' << r.height << ']';
}
int main(int argc, char** argv) {
    try {
        if (argc != 7) throw std::runtime_error(
            "usage: face_image_compare detector.rknn recognizer.rknn old.bgr new.bgr width height");
        const int w = dimension(argv[5]), h = dimension(argv[6]);
        auto old_image = read_bgr(argv[3], w, h), new_image = read_bgr(argv[4], w, h);
        cv::setNumThreads(1);
        rknn::RknnBackend detector(argv[1], rtctrl::inference::TensorType::UInt8);
        rknn::RknnBackend recognizer(argv[2], rtctrl::inference::TensorType::UInt8);
        auto old_faces = rtctrl::face::detect(detector, old_image, 0.8f, 1024);
        auto new_faces = rtctrl::face::detect(detector, new_image, 0.8f, 1024);
        struct Pair { std::size_t a, b; float iou; };
        std::vector<Pair> candidates;
        for (std::size_t a = 0; a < old_faces.size(); ++a)
            for (std::size_t b = 0; b < new_faces.size(); ++b)
                candidates.push_back({a, b, overlap(old_faces[a].box, new_faces[b].box)});
        std::stable_sort(candidates.begin(), candidates.end(),
            [](const Pair& a, const Pair& b) { return a.iou > b.iou; });
        std::vector<bool> used_old(old_faces.size()), used_new(new_faces.size());
        std::vector<Pair> pairs;
        for (const auto& p : candidates) {
            if (p.iou <= 0 || used_old[p.a] || used_new[p.b]) continue;
            pairs.push_back(p);
            used_old[p.a] = used_new[p.b] = true;
        }
        // Compute before writing JSON so inference failures cannot emit partial reports.
        std::vector<double> cosines;
        for (const auto& p : pairs) {
            auto a = rtctrl::face::embed(recognizer, old_image, old_faces[p.a]);
            auto b = rtctrl::face::embed(recognizer, new_image, new_faces[p.b]);
            double dot = 0, aa = 0, bb = 0;
            for (std::size_t i = 0; i < a.size(); ++i) {
                dot += double(a[i]) * b[i]; aa += double(a[i]) * a[i]; bb += double(b[i]) * b[i];
            }
            cosines.push_back(std::clamp(dot / std::sqrt(aa * bb), -1.0, 1.0));
        }
        bool complete = !pairs.empty() && pairs.size() == old_faces.size() &&
                        pairs.size() == new_faces.size();
        std::cout << std::setprecision(9)
                  << "{\"status\":\"" << (complete ? "measured_not_accuracy_validation" :
                      pairs.empty() ? "embedding_unverified_no_matched_faces" : "incomplete_face_matching")
                  << "\",\"same_face_count\":" << (old_faces.size() == new_faces.size() ? "true" : "false")
                  << ",\"old_count\":" << old_faces.size() << ",\"new_count\":" << new_faces.size()
                  << ",\"matching\":\"greedy_highest_positive_iou\",\"pairs\":[";
        for (std::size_t i = 0; i < pairs.size(); ++i) {
            const auto& p = pairs[i];
            const auto& a = old_faces[p.a]; const auto& b = new_faces[p.b];
            if (i) std::cout << ',';
            std::cout << "{\"old_index\":" << p.a << ",\"new_index\":" << p.b
                      << ",\"iou\":" << p.iou << ",\"old_confidence\":" << a.confidence
                      << ",\"new_confidence\":" << b.confidence
                      << ",\"embedding_cosine\":" << cosines[i] << ",\"old_box\":";
            box(a.box); std::cout << ",\"new_box\":"; box(b.box); std::cout << '}';
        }
        std::cout << "],\"unmatched_old\":[";
        bool first = true;
        for (std::size_t i = 0; i < used_old.size(); ++i) if (!used_old[i]) {
            if (!first) std::cout << ','; first = false; std::cout << i;
        }
        std::cout << "],\"unmatched_new\":["; first = true;
        for (std::size_t i = 0; i < used_new.size(); ++i) if (!used_new[i]) {
            if (!first) std::cout << ','; first = false; std::cout << i;
        }
        std::cout << "]}\n";
        return complete ? 0 : 2;
    } catch (const std::exception& e) {
        std::cerr << "face_image_compare: " << e.what() << '\n';
        return 1;
    }
}
