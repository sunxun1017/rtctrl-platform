#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace rtctrl::hal {

constexpr std::size_t kActuatorPacketPayloadCapacity = 256;
constexpr std::size_t kActuatorPacketBatchCapacity = 128;

// A protocol data unit addressed to a logical actuator endpoint. It contains
// no serial device path, baud rate, CAN identifier, EtherCAT PDO offset, or
// vendor SDK type. Those mappings belong to an IActuatorLink adapter.
struct ActuatorPacket {
    std::uint16_t endpoint{0};
    std::uint16_t size{0};
    std::array<std::byte, kActuatorPacketPayloadCapacity> payload{};
    std::int64_t timestamp_ns{0};
};

class ActuatorPacketBatch final {
  public:
    void clear() noexcept {
        size_ = 0;
    }
    bool push(const ActuatorPacket& packet) noexcept {
        if (size_ == packets_.size() || packet.size > packet.payload.size()) {
            return false;
        }
        packets_[size_++] = packet;
        return true;
    }

    std::size_t size() const noexcept {
        return size_;
    }
    bool empty() const noexcept {
        return size_ == 0;
    }
    const ActuatorPacket& operator[](std::size_t index) const noexcept {
        return packets_[index];
    }
    ActuatorPacket& operator[](std::size_t index) noexcept {
        return packets_[index];
    }

  private:
    std::array<ActuatorPacket, kActuatorPacketBatchCapacity> packets_{};
    std::size_t size_{0};
};

enum class ActuatorLinkStatus : std::uint8_t {
    Ok,
    WouldBlock,
    Closed,
    Error,
};

struct ActuatorLinkCapabilities {
    std::size_t max_payload_size{0};
    std::size_t max_packets_per_cycle{0};
};

// Implementations adapt native link semantics without leaking them upward:
// serial framing over IByteTransport, CAN-ID routing over ICanTransport, or
// endpoint/PDO routing over an IgH process image.
class IActuatorLink {
  public:
    virtual ~IActuatorLink() = default;

    // Queried only by the composition root before the realtime threads start.
    virtual ActuatorLinkCapabilities capabilities() const noexcept = 0;
    // open() configures resources but must not energize an actuator.
    virtual ActuatorLinkStatus open() noexcept = 0;
    virtual ActuatorLinkStatus receive(std::int64_t now_ns,
                                       ActuatorPacketBatch& packets) noexcept = 0;
    virtual ActuatorLinkStatus transmit(std::int64_t now_ns,
                                        const ActuatorPacketBatch& packets) noexcept = 0;
    virtual void close() noexcept = 0;
};

} // namespace rtctrl::hal
