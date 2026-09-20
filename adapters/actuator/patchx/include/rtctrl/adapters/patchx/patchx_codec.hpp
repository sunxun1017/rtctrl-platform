#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace rtctrl::patchx {

// Local capacity, not a claimed MCU limit: accommodates the observed firmware
// block's 4-byte metadata and 256 bytes of data. No physical I/O or motor units.
constexpr std::size_t kMaxPayload = 260;
constexpr std::size_t kMaxWireFrame = kMaxPayload + 9;

struct Packet {
    std::uint8_t command{0};
    std::array<std::byte, kMaxPayload> payload{};
    std::size_t payload_size{0};
};

struct WireFrame {
    std::array<std::byte, kMaxWireFrame> bytes{};
    std::size_t size{0};
};

// FF FF | BE16(command + payload length) | command | payload |
// BE16(CRC16/Modbus over length + command + payload) | 55 AA.
// Failure sets output.size to zero. A zero-size payload may have a null pointer.
// Encoding a command does not establish its safety, units, or ACK semantics.
bool encode_frame(std::uint8_t command,
                  const std::byte* payload,
                  std::size_t payload_size,
                  WireFrame& output) noexcept;

// Fixed-storage parser for a non-real-time ingress worker. push is all-or-none;
// on overflow drain with pop before retrying, or reset after a transport gap.
// pop validates framing/CRC only, not firmware/command-specific semantics.
// A plausible incomplete length waits for more bytes. The caller owns the
// inter-byte deadline and must reset on timeout/reconnect to discard stale data.
class StreamParser final {
  public:
    static constexpr std::size_t kCapacity = kMaxWireFrame * 2;

    bool push(const std::byte* data, std::size_t size) noexcept;
    // A false result leaves the output packet unchanged.
    bool pop(Packet& output) noexcept;
    void reset() noexcept {
        size_ = 0;
    }
    std::size_t buffered_size() const noexcept {
        return size_;
    }

  private:
    void discard(std::size_t count) noexcept;
    std::array<std::byte, kCapacity> buffer_{};
    std::size_t size_{0};
};

} // namespace rtctrl::patchx
