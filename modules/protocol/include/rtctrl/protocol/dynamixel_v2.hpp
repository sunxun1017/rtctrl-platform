#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace rtctrl::protocol {

constexpr std::size_t kDynamixelV2MaxWirePacket = 512;
constexpr std::size_t kDynamixelV2MaxParameters = 256;
constexpr std::uint8_t kDynamixelBroadcastId = 0xfeU;
constexpr std::uint8_t kDynamixelStatusInstruction = 0x55U;

enum class DynamixelV2Instruction : std::uint8_t {
    Ping = 0x01,
    Read = 0x02,
    Write = 0x03,
    SyncRead = 0x82,
    SyncWrite = 0x83,
    BulkRead = 0x92,
    BulkWrite = 0x93,
};

struct DynamixelV2Packet {
    std::uint8_t id{0};
    std::uint8_t instruction{0};
    std::uint8_t error{0};
    std::array<std::byte, kDynamixelV2MaxParameters> parameters{};
    std::size_t parameter_size{0};
};

std::uint16_t dynamixel_v2_crc16(const std::byte* data, std::size_t size) noexcept;

bool encode_dynamixel_v2_packet(std::uint8_t id, std::uint8_t instruction,
                                const std::byte* parameters, std::size_t parameter_size,
                                std::byte* output, std::size_t capacity,
                                std::size_t& output_size) noexcept;

class DynamixelV2StreamParser final {
  public:
    bool push(const std::byte* data, std::size_t size) noexcept;
    bool pop(DynamixelV2Packet& packet) noexcept;
    void reset() noexcept {
        size_ = 0;
    }
    std::size_t buffered_size() const noexcept {
        return size_;
    }

  private:
    void discard(std::size_t size) noexcept;

    std::array<std::byte, kDynamixelV2MaxWirePacket * 2U> buffer_{};
    std::size_t size_{0};
};

} // namespace rtctrl::protocol
