#include "digest.hpp"
#include "pipeline.hpp"
#include "rtctrl/adapters/rknn/backend.hpp"
#include <cmath>
#include <iostream>
#include <map>
#include <opencv2/imgcodecs.hpp>
#include <sstream>
#include <stdexcept>
int main(int argc, char** argv) {
    try {
        if (argc < 2)
            throw std::runtime_error(
                "usage: rtctrl_face enroll|recognize --detector FILE --recognizer "
                "FILE --image FILE --gallery FILE [--name NAME | --threshold VALUE "
                "--gap VALUE]");
        std::string action = argv[1];
        if (action != "enroll" && action != "recognize")
            throw std::runtime_error("unknown action");
        std::map<std::string, std::string> args;
        for (int i = 2; i < argc; i += 2) {
            if (i + 1 >= argc || !args.emplace(argv[i], argv[i + 1]).second)
                throw std::runtime_error("missing or duplicate option");
        }
        for (const auto& a : args)
            if (a.first != "--detector" && a.first != "--recognizer" &&
                a.first != "--image" && a.first != "--gallery" &&
                a.first != "--name" && a.first != "--threshold" &&
                a.first != "--gap")
                throw std::runtime_error("unknown option: " + a.first);
        auto get = [&](const std::string& k) -> const std::string& {
            auto it = args.find(k);
            if (it == args.end() || it->second.empty())
                throw std::runtime_error("required option: " + k);
            return it->second;
        };
        auto number = [&](const std::string& k) {
            const auto& s = get(k);
            std::size_t end = 0;
            float v = std::stof(s, &end);
            if (end != s.size())
                throw std::runtime_error("invalid numeric option");
            return v;
        };
        float threshold = action == "recognize" ? number("--threshold") : 0,
              gap = args.count("--gap") ? number("--gap") : 0;
        if (!std::isfinite(threshold) || threshold < -1 || threshold > 1 ||
            !std::isfinite(gap) || gap < 0 || gap > 2)
            throw std::runtime_error("invalid threshold or gap");
        auto gallery = rtctrl::face::load_gallery(
            get("--gallery"),
            rtctrl::face::model_fingerprint(get("--recognizer")),
            action == "enroll");
        cv::Mat image = cv::imread(get("--image"));
        if (image.empty())
            throw std::runtime_error("cannot read image");
        rknn::RknnBackend detector(get("--detector").c_str()),
            recognizer(get("--recognizer").c_str());
        auto faces = rtctrl::face::detect(detector, image);
        if (action == "enroll") {
            if (faces.size() != 1)
                throw std::runtime_error(
                    "enrollment requires exactly one detected face");
            auto embedding = rtctrl::face::embed(recognizer, image, faces[0]);
            if (gallery.dimension && gallery.dimension != embedding.size())
                throw std::runtime_error("gallery dimension mismatch");
            gallery.dimension = embedding.size();
            gallery.samples.push_back({get("--name"), embedding});
            rtctrl::face::save_gallery(get("--gallery"), gallery);
            std::cout << "{\"enrolled\":" << rtctrl::face::json_string(get("--name"))
                      << "}\n";
        } else {
            std::ostringstream result;
            result << "{\"faces\":[";
            bool first = true;
            for (const auto& f : faces) {
                auto embedding = rtctrl::face::embed(recognizer, image, f);
                auto match = rtctrl::face::match(gallery, embedding, threshold, gap);
                if (!first)
                    result << ',';
                first = false;
                result << "{\"name\":" << rtctrl::face::json_string(match.name)
                       << ",\"similarity\":" << match.similarity
                       << ",\"confidence\":" << f.confidence << ",\"box\":["
                       << f.box.x << ',' << f.box.y << ',' << f.box.width << ','
                       << f.box.height << "],\"landmarks\":[";
                for (int i = 0; i < 5; ++i) {
                    if (i)
                        result << ',';
                    result << '[' << f.landmarks[i].x << ',' << f.landmarks[i].y
                           << ']';
                }
                result << "]}";
            }
            result << "]}\n";
            std::cout << result.str();
        }
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "face recognition: " << e.what() << '\n';
        return 1;
    }
}
