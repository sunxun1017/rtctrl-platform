#include "mpp_jpeg.hpp"
#include <stdexcept>
int main() {
    if (rtctrl::face::MppJpegEncoder::compiled())
        return 1;
    try {
        rtctrl::face::MppJpegEncoder encoder;
    } catch (const std::runtime_error&) {
        return 0;
    }
    return 1;
}
