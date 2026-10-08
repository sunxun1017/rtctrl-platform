#pragma once
#include "rtctrl/inference/backend.hpp"
#include <array>
#include <opencv2/core.hpp>
#include <string>
#include <vector>
namespace rtctrl::face {
struct Face {
    cv::Rect2f box;
    std::array<cv::Point2f, 5> landmarks;
    float confidence;
};
struct Sample {
    std::string name;
    std::vector<float> embedding;
};
struct Gallery {
    std::string model_id;
    std::size_t dimension = 0;
    std::vector<Sample> samples;
};
struct Match {
    std::string name = "unknown";
    float similarity = -1;
};
void normalize(std::vector<float>& values);
cv::Mat align_face(const cv::Mat& bgr, const Face& face);
/**
 * @brief
 * 输入一张图片，返回检测到的人脸框、置信度和五个关键点，但是不负责告诉我们这个人是谁，并没有生成特征向量
 *
 * @param backend 推理后端
 * @param bgr     输入图片，按BGR通道顺序解释
 * @param threshold 检测置信度阈值，低于它的候选框被丢弃
 * @param max_faces 最多返回多少张人脸
 * @return std::vector<Face>
 */
std::vector<Face> detect(inference::Backend& backend,
                         const cv::Mat& bgr,
                         float threshold = 0.8f,
                         std::size_t max_faces = 32);
std::vector<float>
embed(inference::Backend& backend, const cv::Mat& bgr, const Face& face);
void enroll(Gallery& gallery,
            const std::string& name,
            inference::Backend& detector,
            inference::Backend& recognizer,
            const cv::Mat& bgr);
Match match(const Gallery& gallery,
            const std::vector<float>& embedding,
            float threshold,
            float gap = 0);
Gallery load_gallery(const std::string& path,
                     const std::string& model_id,
                     bool allow_missing = false);
void save_gallery(const std::string& path, const Gallery& gallery);
std::string json_string(const std::string& text);
} // namespace rtctrl::face
