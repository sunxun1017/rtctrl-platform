#include "rtctrl/hal/protocol_actuator_hal.hpp"

namespace rtctrl::hal {

HalStatus ProtocolActuatorHal::map_link_status(ActuatorLinkStatus status) noexcept {
    switch (status) {
        case ActuatorLinkStatus::Ok:
            return HalStatus::Ok;
        case ActuatorLinkStatus::WouldBlock:
            return HalStatus::NotReady;
        case ActuatorLinkStatus::Closed:
        case ActuatorLinkStatus::Error:
            return HalStatus::IoError;
    }
    return HalStatus::IoError;
}

HalStatus ProtocolActuatorHal::map_protocol_status(ActuatorProtocolStatus status) noexcept {
    switch (status) {
        case ActuatorProtocolStatus::Ok:
            return HalStatus::Ok;
        case ActuatorProtocolStatus::NotReady:
            return HalStatus::NotReady;
        case ActuatorProtocolStatus::InvalidData:
            return HalStatus::IoError;
    }
    return HalStatus::IoError;
}

HalStatus ProtocolActuatorHal::open_safe(std::int64_t now_ns) noexcept {
    if (open_) {
        return HalStatus::NotReady;
    }
    protocol_.reset();
    receive_packets_.clear();
    transmit_packets_.clear();
    const auto result = map_link_status(link_.open());
    if (result != HalStatus::Ok) {
        link_.close();
        return result;
    }
    open_ = true;
    feedback_ready_ = false;
    armed_ = false;
    const auto startup_status =
        map_protocol_status(protocol_.encode_startup(now_ns, transmit_packets_));
    if (startup_status != HalStatus::Ok) {
        close();
        return startup_status;
    }
    if (!transmit_packets_.empty()) {
        const auto transmit_status = map_link_status(link_.transmit(now_ns, transmit_packets_));
        if (transmit_status != HalStatus::Ok) {
            close();
            return transmit_status;
        }
    }
    return HalStatus::Ok;
}

HalStatus ProtocolActuatorHal::arm(std::int64_t now_ns) noexcept {
    if (!open_ || !feedback_ready_ || armed_) {
        return HalStatus::NotReady;
    }
    transmit_packets_.clear();
    auto result = map_protocol_status(protocol_.encode_arm(now_ns, transmit_packets_));
    if (result != HalStatus::Ok) {
        return result;
    }
    result = map_link_status(link_.transmit(now_ns, transmit_packets_));
    if (result == HalStatus::Ok) {
        armed_ = true;
    }
    return result;
}

HalStatus ProtocolActuatorHal::read(std::int64_t now_ns, model::SensorFrame& output) noexcept {
    if (!open_) {
        return HalStatus::NotReady;
    }
    receive_packets_.clear();
    const auto link_result = map_link_status(link_.receive(now_ns, receive_packets_));
    if (link_result != HalStatus::Ok) {
        return link_result;
    }
    const auto result =
        map_protocol_status(protocol_.decode_feedback(now_ns, receive_packets_, output));
    if (result == HalStatus::Ok) {
        feedback_ready_ = true;
    }
    return result;
}

HalStatus ProtocolActuatorHal::write(std::int64_t now_ns,
                                     const model::CommandFrame& input) noexcept {
    if (!open_ || !armed_) {
        return HalStatus::NotReady;
    }
    transmit_packets_.clear();
    const auto protocol_result =
        map_protocol_status(protocol_.encode_command(now_ns, input, transmit_packets_));
    if (protocol_result != HalStatus::Ok) {
        return protocol_result;
    }
    return map_link_status(link_.transmit(now_ns, transmit_packets_));
}

void ProtocolActuatorHal::emergency_stop(std::int64_t now_ns) noexcept {
    if (!open_) {
        return;
    }
    transmit_packets_.clear();
    if (protocol_.encode_safe_stop(now_ns, transmit_packets_) == ActuatorProtocolStatus::Ok) {
        (void)link_.transmit(now_ns, transmit_packets_);
    }
    armed_ = false;
    feedback_ready_ = false;
}

void ProtocolActuatorHal::close() noexcept {
    armed_ = false;
    feedback_ready_ = false;
    if (open_) {
        link_.close();
    }
    open_ = false;
    receive_packets_.clear();
    transmit_packets_.clear();
}

} // namespace rtctrl::hal
