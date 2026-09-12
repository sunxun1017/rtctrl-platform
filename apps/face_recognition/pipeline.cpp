#include "pipeline.hpp"
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <map>
#include <opencv2/imgproc.hpp>
#include <stdexcept>
#include <unistd.h>
namespace rtctrl::face {
namespace {
void require(bool ok, const char* message) {
    if (!ok)
        throw std::runtime_error(message);
}
void submit(inference::Backend& backend, const cv::Mat& bgr, int side) {
    require(!bgr.empty() && bgr.type() == CV_8UC3, "expected nonempty BGR8 image");
    require(backend.input_count() == 1, "model must have exactly one input");
    const auto& s = backend.input_spec(0);
    using L = inference::TensorLayout;
    require(s.type == inference::TensorType::Float32 ||
                s.type == inference::TensorType::UInt8,
            "expected float32 or uint8 submission");
    std::vector<std::uint32_t> expected =
        s.layout == L::NCHW
            ? std::vector<std::uint32_t>{1, 3, (unsigned)side, (unsigned)side}
            : std::vector<std::uint32_t>{1, (unsigned)side, (unsigned)side, 3};
    require((s.layout == L::NCHW || s.layout == L::NHWC) && s.shape == expected,
            "unexpected model input shape/layout");
    require(bgr.rows == side && bgr.cols == side, "unexpected image size");
    auto view = backend.get_input_buffer(0);
    require(view.data && view.type == s.type && view.size_bytes == s.byte_size(),
            "invalid writable input view");
    for (int y = 0; y < side; ++y)
        for (int x = 0; x < side; ++x)
            for (int c = 0; c < 3; ++c) {
                auto i = s.layout == L::NCHW ? c * side * side + y * side + x
                                             : (y * side + x) * 3 + c;
                const auto value = bgr.at<cv::Vec3b>(y, x)[2 - c];
                if (s.type == inference::TensorType::Float32)
                    static_cast<float*>(view.data)[i] = value;
                else
                    static_cast<unsigned char*>(view.data)[i] = value;
            }
    require(backend.commit_input(0) && backend.run(), "inference failed");
}
float iou(const cv::Rect2f& a, const cv::Rect2f& b) {
    float intersection = (a & b).area();
    return intersection / (a.area() + b.area() - intersection);
}
} // namespace
void normalize(std::vector<float>& v) {
    double n = 0;
    require(!v.empty(), "empty embedding");
    for (float x : v) {
        require(std::isfinite(x), "nonfinite embedding");
        n += double(x) * x;
    }
    require(n > 1e-20, "zero embedding");
    n = std::sqrt(n);
    for (float& x : v)
        x = float(x / n);
}
cv::Mat align_face(const cv::Mat& bgr, const Face& face) {
    static const cv::Point2f dst[5] = {{38.2946f, 51.6963f},
                                       {73.5318f, 51.5014f},
                                       {56.0252f, 71.7366f},
                                       {41.5493f, 92.3655f},
                                       {70.7299f, 92.2041f}};
    cv::Mat a = cv::Mat::zeros(10, 4, CV_64F), b(10, 1, CV_64F);
    for (int i = 0; i < 5; ++i) {
        double x = face.landmarks[i].x, y = face.landmarks[i].y;
        require(std::isfinite(x) && std::isfinite(y), "invalid landmarks");
        a.at<double>(2 * i, 0) = x;
        a.at<double>(2 * i, 1) = -y;
        a.at<double>(2 * i, 2) = 1;
        a.at<double>(2 * i + 1, 0) = y;
        a.at<double>(2 * i + 1, 1) = x;
        a.at<double>(2 * i + 1, 3) = 1;
        b.at<double>(2 * i) = dst[i].x;
        b.at<double>(2 * i + 1) = dst[i].y;
    }
    cv::SVD svd(a);
    require(svd.w.at<double>(3) > 1e-8, "degenerate landmarks");
    cv::Mat p;
    require(cv::solve(a, b, p, cv::DECOMP_SVD), "alignment failed");
    double u = p.at<double>(0), v = p.at<double>(1);
    require(u * u + v * v > 1e-12, "degenerate alignment");
    cv::Mat m =
        (cv::Mat_<double>(2, 3) << u, -v, p.at<double>(2), v, u, p.at<double>(3));
    cv::Mat result;
    cv::warpAffine(bgr, result, m, {112, 112});
    return result;
}
std::vector<Face> detect(inference::Backend& backend,
                         const cv::Mat& bgr,
                         float threshold,
                         std::size_t max_faces) {
    require(!bgr.empty() && bgr.type() == CV_8UC3, "expected BGR8 image");
    require(threshold > 0 && threshold <= 1 && max_faces > 0 && max_faces <= 1024,
            "invalid detection limits");
    float scale = std::min(320.f / bgr.cols, 320.f / bgr.rows);
    int w = std::max(1, int(std::round(bgr.cols * scale))),
        h = std::max(1, int(std::round(bgr.rows * scale)));
    int left = (320 - w) / 2, top = (320 - h) / 2;
    cv::Mat image(320, 320, CV_8UC3, cv::Scalar(0, 0, 0)), resized;
    cv::resize(bgr, resized, {w, h});
    resized.copyTo(image(cv::Rect(left, top, w, h)));
    submit(backend, image, 320);
    constexpr std::size_t count = 4200;
    const std::vector<float>*loc = nullptr, *conf = nullptr, *land = nullptr;
    require(backend.output_count() == 3, "expected three RetinaFace outputs");
    for (std::size_t i = 0; i < 3; ++i) {
        const auto& s = backend.output_spec(i);
        const auto& v = backend.output_data(i);
        require(s.type == inference::TensorType::Float32, "expected float output");
        std::vector<std::uint32_t> shape = s.shape;
        if (shape.size() == 3 && shape[0] == 1)
            shape.erase(shape.begin());
        require(shape.size() == 2 && shape[0] == count,
                "expected anchor-major RetinaFace output");
        if (shape[1] == 4 && !loc)
            loc = &v;
        else if (shape[1] == 2 && !conf)
            conf = &v;
        else if (shape[1] == 10 && !land)
            land = &v;
        else
            throw std::runtime_error("ambiguous RetinaFace outputs");
        require(v.size() == count * shape[1], "output length mismatch");
        for (float x : v)
            require(std::isfinite(x), "nonfinite detection output");
    }
    require(loc && conf && land, "missing RetinaFace output");
    std::vector<Face> candidates;
    std::size_t n = 0;
    int steps[] = {8, 16, 32};
    int sizes[][2] = {{16, 32}, {64, 128}, {256, 512}};
    for (int k = 0; k < 3; ++k)
        for (int y = 0; y < 320 / steps[k]; ++y)
            for (int x = 0; x < 320 / steps[k]; ++x)
                for (int size : sizes[k]) {
                    std::size_t i = n++;
                    float score = (*conf)[2 * i + 1];
                    require(score >= 0 && score <= 1,
                            "confidence must be probability");
                    if (score < threshold)
                        continue;
                    float cx = (x + .5f) * steps[k], cy = (y + .5f) * steps[k];
                    float bw = size * std::exp((*loc)[4 * i + 2] * .2f),
                          bh = size * std::exp((*loc)[4 * i + 3] * .2f);
                    float bx = cx + (*loc)[4 * i] * .1f * size,
                          by = cy + (*loc)[4 * i + 1] * .1f * size;
                    require(std::isfinite(bw) && std::isfinite(bh),
                            "invalid decoded box");
                    float sx = float(bgr.cols) / w, sy = float(bgr.rows) / h;
                    Face f;
                    f.confidence = score;
                    f.box = cv::Rect2f((bx - bw / 2 - left) * sx,
                                       (by - bh / 2 - top) * sy,
                                       bw * sx,
                                       bh * sy) &
                            cv::Rect2f(0, 0, float(bgr.cols), float(bgr.rows));
                    if (f.box.area() <= 0)
                        continue;
                    for (int j = 0; j < 5; ++j)
                        f.landmarks[j] = {
                            (cx + (*land)[10 * i + 2 * j] * .1f * size - left) * sx,
                            (cy + (*land)[10 * i + 2 * j + 1] * .1f * size - top) *
                                sy};
                    candidates.push_back(f);
                }
    std::stable_sort(
        candidates.begin(), candidates.end(), [](const Face& a, const Face& b) {
            return a.confidence > b.confidence;
        });
    if (candidates.size() > 1000)
        candidates.resize(1000);
    std::vector<Face> result;
    for (const auto& f : candidates) {
        bool keep = true;
        for (const auto& r : result)
            if (iou(f.box, r.box) > .4f) {
                keep = false;
                break;
            }
        if (keep) {
            result.push_back(f);
            if (result.size() == max_faces)
                break;
        }
    }
    return result;
}
std::vector<float>
embed(inference::Backend& backend, const cv::Mat& bgr, const Face& face) {
    submit(backend, align_face(bgr, face), 112);
    require(backend.output_count() == 1, "expected one embedding output");
    auto result = backend.output_data(0);
    require(result.size() == 512,
            "expected 512-dimensional MobileFaceNet embedding");
    normalize(result);
    return result;
}
void enroll(Gallery& g,
            const std::string& name,
            inference::Backend& detector,
            inference::Backend& recognizer,
            const cv::Mat& bgr) {
    require(!name.empty() && name != "unknown", "invalid enrollment name");
    auto faces = detect(detector, bgr);
    require(faces.size() == 1, "enrollment requires exactly one detected face");
    auto embedding = embed(recognizer, bgr, faces[0]);
    require(!g.dimension || g.dimension == embedding.size(),
            "gallery dimension mismatch");
    g.dimension = embedding.size();
    g.samples.push_back({name, std::move(embedding)});
}
Match match(const Gallery& g,
            const std::vector<float>& input,
            float threshold,
            float gap) {
    require(std::isfinite(threshold) && threshold >= -1 && threshold <= 1 &&
                std::isfinite(gap) && gap >= 0 && gap <= 2,
            "invalid match threshold/gap");
    require(input.size() == g.dimension, "embedding dimension mismatch");
    auto v = input;
    normalize(v);
    std::map<std::string, float> scores;
    for (const auto& s : g.samples) {
        require(s.embedding.size() == v.size(), "gallery dimension mismatch");
        auto e = s.embedding;
        normalize(e);
        float score = 0;
        for (std::size_t i = 0; i < v.size(); ++i)
            score += v[i] * e[i];
        auto it = scores.find(s.name);
        if (it == scores.end() || score > it->second)
            scores[s.name] = score;
    }
    Match result;
    float second = -1;
    for (const auto& s : scores) {
        if (s.second > result.similarity) {
            second = result.similarity;
            result = {s.first, s.second};
        } else
            second = std::max(second, s.second);
    }
    if (result.similarity < threshold || result.similarity - second < gap ||
        (scores.size() > 1 && second >= result.similarity))
        result.name = "unknown";
    return result;
}
Gallery load_gallery(const std::string& path, const std::string& id, bool missing) {
    require(!id.empty(), "empty model id");
    if (!std::filesystem::exists(path)) {
        require(missing, "gallery does not exist");
        return {id, 0, {}};
    }
    cv::FileStorage fs(path, cv::FileStorage::READ);
    require(fs.isOpened(), "cannot read gallery");
    Gallery g;
    int version = 0, dim = 0;
    fs["version"] >> version;
    fs["model_id"] >> g.model_id;
    fs["dimension"] >> dim;
    require(version == 1 && g.model_id == id && dim > 0 && dim <= 65536,
            "invalid gallery or model mismatch");
    g.dimension = dim;
    auto samples = fs["samples"];
    require(samples.isSeq() && !samples.empty(), "invalid gallery samples");
    for (const auto& node : samples) {
        Sample s;
        node["name"] >> s.name;
        node["embedding"] >> s.embedding;
        require(!s.name.empty() && s.name != "unknown" &&
                    s.embedding.size() == g.dimension,
                "invalid gallery sample");
        normalize(s.embedding);
        g.samples.push_back(std::move(s));
    }
    return g;
}
void save_gallery(const std::string& path, const Gallery& g) {
    require(!g.model_id.empty() && g.dimension > 0 && !g.samples.empty(),
            "invalid gallery");
    std::string pattern = path + ".tmp.XXXXXX";
    std::vector<char> temp(pattern.begin(), pattern.end());
    temp.push_back(0);
    int fd = mkstemp(temp.data());
    require(fd >= 0, "cannot create gallery temporary file");
    close(fd);
    try {
        cv::FileStorage fs(temp.data(),
                           cv::FileStorage::WRITE | cv::FileStorage::FORMAT_JSON);
        require(fs.isOpened(), "cannot write gallery");
        fs << "version" << 1 << "model_id" << g.model_id << "dimension"
           << int(g.dimension) << "samples" << "[";
        for (const auto& s : g.samples) {
            require(!s.name.empty() && s.name != "unknown" &&
                        s.embedding.size() == g.dimension,
                    "invalid gallery sample");
            auto e = s.embedding;
            normalize(e);
            fs << "{" << "name" << s.name << "embedding" << e << "}";
        }
        fs << "]";
        fs.release();
        std::filesystem::rename(temp.data(), path);
    } catch (...) {
        std::filesystem::remove(temp.data());
        throw;
    }
}
std::string json_string(const std::string& s) {
    std::string out = "\"";
    const char* hex = "0123456789abcdef";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') {
            out += '\\';
            out += char(c);
        } else if (c < 32) {
            out += "\\u00";
            out += hex[c >> 4];
            out += hex[c & 15];
        } else
            out += char(c);
    }
    return out + '"';
}
} // namespace rtctrl::face
