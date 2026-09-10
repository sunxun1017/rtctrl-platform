#include "rtctrl/products/yidong23/topology.hpp"
#include <cstdio>

namespace {
int failures = 0;
void expect(bool condition, const char* message) {
    if (!condition) {
        std::fprintf(stderr, "%s\n", message);
        ++failures;
    }
}
void test_yidong_topology() {
    constexpr auto& topology = rtctrl::profiles::yidong23::kTopology;
    static_assert(topology.valid());
    const auto* waist_pitch = topology.for_logical_joint(13);
    expect(waist_pitch != nullptr && waist_pitch->master_id == 2 &&
               waist_pitch->motor_index == 5 &&
               waist_pitch->calibration.protocol == rtctrl::hal::MotorProtocol::Ti5,
           "Yidong logical joint maps to the reviewed physical EtherCAT slot");
    const auto* left_hip = topology.for_physical_motor(0, 0);
    expect(left_hip != nullptr && left_hip->logical_joint_index == 0 &&
               left_hip->calibration.effort_max == 150.0,
           "motor calibration stays attached to the physical motor route");
}
} // namespace

int main() {
    test_yidong_topology();
    return failures == 0 ? 0 : 1;
}
