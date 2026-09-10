#include "pipeline.hpp"
#include <cmath>
#include <filesystem>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <unistd.h>
using namespace rtctrl;
void check(bool b) {
    if (!b)
        throw std::runtime_error("test failed");
}
template <class F> void rejects(F f) {
    bool caught = false;
    try {
        f();
    } catch (const std::exception&) {
        caught = true;
    }
    check(caught);
}
class Fake : public inference::Backend {
  public:
    inference::TensorSpec input{{1, 320, 320, 3},
                                inference::TensorType::Float32,
                                inference::TensorLayout::NHWC};
    std::vector<inference::TensorSpec> specs = {
        {{1, 4200, 4}}, {{1, 4200, 2}}, {{1, 4200, 10}}};
    std::vector<std::vector<float>> outputs = {std::vector<float>(16800),
                                               std::vector<float>(8400),
                                               std::vector<float>(42000)};
    bool ready = false;
    std::size_t input_count() const noexcept override {
        return 1;
    }
    const inference::TensorSpec& input_spec(std::size_t) const override {
        return input;
    }
    inference::MutableTensorView get_input_buffer(std::size_t) override {
        return {inference::TensorType::Float32, nullptr, 0};
    }
    bool commit_input(std::size_t) override {
        return false;
    }
    bool
    prepare_input_data(const void* p, std::size_t size, std::size_t i) override {
        ready = p && size == input.byte_size() && i == 0;
        return ready;
    }
    bool run() override {
        return ready;
    }
    std::size_t output_count() const noexcept override {
        return outputs.size();
    }
    const inference::TensorSpec& output_spec(std::size_t i) const override {
        return specs.at(i);
    }
    const std::vector<float>& output_data(std::size_t i) const override {
        return outputs.at(i);
    }
};
int main() {
    try {
        std::vector<float> v = {3, 4};
        face::normalize(v);
        check(std::abs(v[0] - .6f) < 1e-6);
        rejects([] {
            std::vector<float> x = {0};
            face::normalize(x);
        });
        rejects([] {
            std::vector<float> x = {std::numeric_limits<float>::quiet_NaN()};
            face::normalize(x);
        });
        face::Gallery g{
            "model",
            2,
            {{"Alice", {1, 0}}, {"Alice", {.99f, .01f}}, {"Bob", {0, 1}}}};
        check(face::match(g, {1, 0}, .8).name == "Alice");
        check(face::match(g, {-1, 0}, .8).name == "unknown");
        check(face::match(g, {1, 1}, .5, .1).name == "unknown");
        face::Gallery tied{"model", 2, {{"Alice", {1, 0}}, {"Bob", {1, 0}}}};
        check(face::match(tied, {1, 0}, .5, 0).name == "unknown");
        rejects([&] { face::match(g, {1}, .5); });
        Fake f;
        cv::Mat image(320, 320, CV_8UC3, cv::Scalar(3, 2, 1));
        check(face::detect(f, image).empty());
        rejects([&] { face::enroll(g, "Test", f, f, image); });
        f.outputs[1][2 * (20 * 40 + 20) * 2 + 1] = .99;
        auto faces = face::detect(f, image);
        check(faces.size() == 1);
        check(std::abs(faces[0].box.x - 156) < 1e-4);
        // A non-square source exercises actual resize scale and padding inversion.
        cv::Mat wide(161, 641, CV_8UC3, cv::Scalar(3, 2, 1));
        auto wide_faces = face::detect(f, wide);
        check(wide_faces.size() == 1);
        check(std::abs(wide_faces[0].box.x - 156.f * 641 / 320) < 1e-3);
        check(std::abs(wide_faces[0].box.y - (156.f - 120) * 161 / 80) < 1e-3);
        // The adjacent anchor is decoded onto the same box and must be suppressed.
        const std::size_t adjacent = (20 * 40 + 21) * 2;
        f.outputs[1][2 * adjacent + 1] = .98;
        f.outputs[0][4 * adjacent] = -5.f;
        check(face::detect(f, image).size() == 1);
        f.outputs[1][2 * adjacent + 1] = 0;
        f.outputs[1][2 * (5 * 40 + 5) * 2 + 1] = .98;
        check(face::detect(f, image).size() == 2);
        rejects([&] { face::enroll(g, "Test", f, f, image); });
        check(face::detect(f, image, .8, 1).size() == 1);
        f.specs[0].shape = {1, 4, 4200};
        rejects([&] { face::detect(f, image); });
        face::Face aligned;
        aligned.landmarks = {cv::Point2f{38.2946f, 51.6963f},
                             {73.5318f, 51.5014f},
                             {56.0252f, 71.7366f},
                             {41.5493f, 92.3655f},
                             {70.7299f, 92.2041f}};
        cv::Mat small(112, 112, CV_8UC3, cv::Scalar(3, 2, 1));
        check(cv::norm(small, face::align_face(small, aligned), cv::NORM_INF) == 0);
        for (auto& p : aligned.landmarks)
            p = {0, 0};
        rejects([&] { face::align_face(small, aligned); });
        std::string path =
            "/tmp/rtctrl-face-test-" + std::to_string(getpid()) + ".json";
        face::save_gallery(path, g);
        check(face::load_gallery(path, "model").samples.size() == 3);
        rejects([&] { face::load_gallery(path, "other"); });
        std::filesystem::remove(path);
        check(face::json_string("a\"\n") == "\"a\\\"\\u000a\"");
        std::cout << "face tests passed\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
