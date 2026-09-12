#pragma once
#include "pipeline.hpp"
namespace rtctrl::face {
inline Match video_match(const Gallery& gallery,
                         const std::vector<float>& embedding,
                         float threshold,
                         float gap) {
    return gallery.samples.empty() ? Match{}
                                   : match(gallery, embedding, threshold, gap);
}
} // namespace rtctrl::face
