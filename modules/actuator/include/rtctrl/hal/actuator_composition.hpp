#pragma once

#include "rtctrl/hal/actuator_link.hpp"
#include "rtctrl/hal/actuator_protocol.hpp"

namespace rtctrl::hal {

// Composition accepts any link implementing the port; transport selection
// belongs to the application, not a backend registry in the actuator module.
struct ActuatorDependencies {
    IActuatorLink* link{nullptr};
    IActuatorProtocol* protocol{nullptr};

    explicit operator bool() const noexcept {
        return link != nullptr && protocol != nullptr;
    }
};

inline ActuatorDependencies
inject_actuator_dependencies(IActuatorLink* link,
                             IActuatorProtocol* protocol) noexcept {
    if (link == nullptr || protocol == nullptr) {
        return {};
    }
    const auto capabilities = link->capabilities();
    const auto requirements = protocol->requirements();
    if (requirements.max_payload_size == 0U ||
        requirements.max_packets_per_cycle == 0U ||
        requirements.max_payload_size > kActuatorPacketPayloadCapacity ||
        requirements.max_packets_per_cycle > kActuatorPacketBatchCapacity ||
        capabilities.max_payload_size < requirements.max_payload_size ||
        capabilities.max_packets_per_cycle < requirements.max_packets_per_cycle) {
        return {};
    }
    return {link, protocol};
}

} // namespace rtctrl::hal
