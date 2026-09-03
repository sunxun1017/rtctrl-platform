#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace rtctrl::hal {

enum class MotorProtocol : std::uint8_t { Encos = 0, Ti5 = 1, Generic = 2 };

struct MotorCalibration {
    MotorProtocol protocol{MotorProtocol::Generic};
    double torque_constant{0.0};
    double gear_ratio{1.0};
    double effort_min{0.0};
    double effort_max{0.0};
    double kd_max{0.0};
};

struct MotorRoute {
    std::uint8_t master_id{0};
    std::uint8_t motor_index{0};
    std::uint8_t logical_joint_index{0};
    MotorCalibration calibration{};
};

template <std::size_t JointCount, std::size_t MasterCount, std::size_t MaxMotorsPerMaster>
struct MotorTopology {
    std::array<MotorRoute, JointCount> routes{};
    std::array<std::uint8_t, MasterCount> motors_per_master{};
    std::array<MotorProtocol, MasterCount> protocol_per_master{};

    constexpr bool valid() const noexcept {
        std::array<std::array<bool, MaxMotorsPerMaster>, MasterCount> physical{};
        std::array<bool, JointCount> logical{};
        for (const auto& route : routes) {
            if (route.master_id >= MasterCount ||
                route.motor_index >= motors_per_master[route.master_id] ||
                route.motor_index >= MaxMotorsPerMaster ||
                route.logical_joint_index >= JointCount ||
                physical[route.master_id][route.motor_index] ||
                logical[route.logical_joint_index] ||
                route.calibration.protocol != protocol_per_master[route.master_id] ||
                route.calibration.gear_ratio <= 0.0 ||
                route.calibration.effort_min >= route.calibration.effort_max ||
                route.calibration.kd_max < 0.0) {
                return false;
            }
            physical[route.master_id][route.motor_index] = true;
            logical[route.logical_joint_index] = true;
        }
        for (std::size_t master = 0; master < MasterCount; ++master) {
            if (motors_per_master[master] > MaxMotorsPerMaster) {
                return false;
            }
            for (std::size_t motor = 0; motor < motors_per_master[master]; ++motor) {
                if (!physical[master][motor]) {
                    return false;
                }
            }
        }
        return true;
    }

    constexpr const MotorRoute* for_logical_joint(std::size_t joint) const noexcept {
        for (const auto& route : routes) {
            if (route.logical_joint_index == joint) {
                return &route;
            }
        }
        return nullptr;
    }

    constexpr const MotorRoute* for_physical_motor(std::size_t master,
                                                   std::size_t motor) const noexcept {
        for (const auto& route : routes) {
            if (route.master_id == master && route.motor_index == motor) {
                return &route;
            }
        }
        return nullptr;
    }
};

} // namespace rtctrl::hal
