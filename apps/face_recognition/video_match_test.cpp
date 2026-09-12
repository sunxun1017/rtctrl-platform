#include "video_match.hpp"
#include <stdexcept>
int main() {
    using namespace rtctrl::face;
    Gallery gallery;
    if (video_match(gallery, {1, 0}, 0.5f, 0).name != "unknown")
        return 1;
    gallery.dimension = 2;
    gallery.samples.push_back({"person", {1, 0}});
    if (video_match(gallery, {1, 0}, 0.5f, 0).name != "person")
        return 2;
    if (video_match(gallery, {0, 1}, 0.5f, 0).name != "unknown")
        return 3;
    try {
        video_match(gallery, {1}, 0.5f, 0);
    } catch (const std::exception&) {
        return 0;
    }
    return 4;
}
