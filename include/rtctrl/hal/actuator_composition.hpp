#pragma once

#include "rtctrl/hal/actuator_link.hpp"
#include "rtctrl/hal/actuator_protocol.hpp"

#include <cstdint>

namespace rtctrl::hal {

// Transport and motor protocol are independent deployment decisions. A motor
// protocol object is injected separately and can be paired with any link whose
// endpoint routing and payload capacity satisfy that protocol's deployment.
enum class ActuatorLinkBackend : std::uint8_t {
    Serial,
    CanFd,
    IghEthercat,
};

struct ActuatorLinkProviders {
    IActuatorLink* serial{nullptr};
    IActuatorLink* can_fd{nullptr};
    IActuatorLink* igh_ethercat{nullptr};
};

struct ActuatorDependencies {
    IActuatorLink* link{nullptr};
    IActuatorProtocol* protocol{nullptr};

    explicit operator bool() const noexcept {
        return link != nullptr && protocol != nullptr;
    }
};

inline IActuatorLink* select_actuator_link(ActuatorLinkBackend backend,
                                           const ActuatorLinkProviders& providers) noexcept {
    switch (backend) {
        case ActuatorLinkBackend::Serial:
            return providers.serial;
        case ActuatorLinkBackend::CanFd:
            return providers.can_fd;
        case ActuatorLinkBackend::IghEthercat:
            return providers.igh_ethercat;
    }
    return nullptr;
}

inline ActuatorDependencies inject_actuator_dependencies(ActuatorLinkBackend backend,
                                                         const ActuatorLinkProviders& providers,
                                                         IActuatorProtocol* protocol) noexcept {
    auto* link = select_actuator_link(backend, providers);
    if (link == nullptr || protocol == nullptr) {
        return {};
    }
    const auto capabilities = link->capabilities();
    const auto requirements = protocol->requirements();
    if (requirements.max_payload_size == 0U || requirements.max_packets_per_cycle == 0U ||
        requirements.max_payload_size > kActuatorPacketPayloadCapacity ||
        requirements.max_packets_per_cycle > kActuatorPacketBatchCapacity ||
        capabilities.max_payload_size < requirements.max_payload_size ||
        capabilities.max_packets_per_cycle < requirements.max_packets_per_cycle) {
        return {};
    }
    return {link, protocol};
}

} // namespace rtctrl::hal
