#include "rga_frame.hpp"
#include <stdexcept>
int main() {
    if (rtctrl::face::RgaFrameConverter::compiled())
        return 1;
    try {
        rtctrl::face::RgaFrameConverter unavailable;
    } catch (const std::runtime_error&) {
        return 0;
    }
    return 1;
}
