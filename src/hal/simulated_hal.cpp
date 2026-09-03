#include "rtctrl/hal/simulated_hal.hpp"

#include <algorithm>

namespace rtctrl::hal {

HalStatus SimulatedHal::open_safe(std::int64_t now_ns) noexcept {
    opened_ = true;
    armed_ = false;
    start_ns_ = now_ns;
    last_update_ns_ = now_ns;
    state_ = {};
    command_ = {};
    return HalStatus::Ok;
}

HalStatus SimulatedHal::arm(std::int64_t) noexcept {
    if (!opened_) {
        return HalStatus::NotReady;
    }
    armed_ = true;
    return HalStatus::Ok;
}

HalStatus SimulatedHal::read(std::int64_t now_ns, model::SensorFrame& output) noexcept {
    if (!opened_) {
        return HalStatus::NotReady;
    }
    if (config_.fault_after_ns > 0 && now_ns - start_ns_ >= config_.fault_after_ns) {
        state_.fault_bits |= 1U;
        output = state_;
        return HalStatus::IoError;
    }

    const auto elapsed_ns = std::max<std::int64_t>(0, now_ns - last_update_ns_);
    const double dt = std::min(0.02, static_cast<double>(elapsed_ns) / 1.0e9);
    for (std::size_t i = 0; i < model::kJointCount; ++i) {
        const double desired = command_.mode == model::CommandMode::Position
                                   ? command_.target_position[i]
                                   : state_.position[i];
        const double kp =
            command_.mode == model::CommandMode::Position ? command_.kp[i] : config_.stiffness;
        const double kd =
            command_.mode == model::CommandMode::Position ? command_.kd[i] : config_.damping;
        const double acceleration =
            command_.effort[i] + kp * (desired - state_.position[i]) - kd * state_.velocity[i];
        state_.velocity[i] += acceleration * dt;
        state_.position[i] += state_.velocity[i] * dt;
        state_.effort[i] = acceleration;
    }
    ++state_.sequence;
    state_.sample_time_ns = now_ns;
    last_update_ns_ = now_ns;
    output = state_;
    return HalStatus::Ok;
}

HalStatus SimulatedHal::write(std::int64_t, const model::CommandFrame& input) noexcept {
    if (!opened_ || !armed_) {
        return HalStatus::NotReady;
    }
    command_ = input;
    return HalStatus::Ok;
}

void SimulatedHal::emergency_stop(std::int64_t now_ns) noexcept {
    command_ = {};
    command_.created_time_ns = now_ns;
    command_.valid_until_ns = now_ns + 1'000'000;
    command_.mode = model::CommandMode::SafeStop;
    for (std::size_t i = 0; i < model::kJointCount; ++i) {
        command_.target_position[i] = state_.position[i];
    }
    armed_ = false;
}

void SimulatedHal::close() noexcept {
    armed_ = false;
    opened_ = false;
    command_ = {};
}

} // namespace rtctrl::hal
