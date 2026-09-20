#include "rtctrl/adapters/patchx/patchx_codec.hpp"

#include <algorithm>
#include <cstring>

namespace rtctrl::patchx {
namespace {
std::uint16_t read_be16(const std::byte* bytes) noexcept {
    return static_cast<std::uint16_t>(
        (std::to_integer<std::uint16_t>(bytes[0]) << 8U) |
        std::to_integer<std::uint16_t>(bytes[1]));
}

void write_be16(std::byte* bytes, std::uint16_t value) noexcept {
    bytes[0] = static_cast<std::byte>(value >> 8U);
    bytes[1] = static_cast<std::byte>(value & 0xffU);
}

std::uint16_t crc16(const std::byte* data, std::size_t size) noexcept {
    std::uint16_t crc = 0xffffU;
    for (std::size_t i = 0; i < size; ++i) {
        crc ^= std::to_integer<std::uint16_t>(data[i]);
        for (unsigned bit = 0; bit < 8U; ++bit) {
            const bool low = (crc & 1U) != 0U;
            crc = static_cast<std::uint16_t>(crc >> 1U);
            if (low)
                crc ^= 0xa001U;
        }
    }
    return crc;
}
} // namespace

bool encode_frame(std::uint8_t command,
                  const std::byte* payload,
                  std::size_t payload_size,
                  WireFrame& output) noexcept {
    output.size = 0;
    if (payload_size > kMaxPayload || (payload_size != 0 && payload == nullptr)) {
        return false;
    }
    // Stage into separate storage so the caller may reuse the previous frame
    // as a payload without overlapping copies or partially replacing it.
    WireFrame encoded{};
    encoded.bytes[0] = std::byte{0xff};
    encoded.bytes[1] = std::byte{0xff};
    write_be16(encoded.bytes.data() + 2,
               static_cast<std::uint16_t>(payload_size + 1));
    encoded.bytes[4] = static_cast<std::byte>(command);
    if (payload_size != 0)
        std::memcpy(encoded.bytes.data() + 5, payload, payload_size);
    write_be16(encoded.bytes.data() + 5 + payload_size,
               crc16(encoded.bytes.data() + 2, payload_size + 3));
    encoded.bytes[7 + payload_size] = std::byte{0x55};
    encoded.bytes[8 + payload_size] = std::byte{0xaa};
    encoded.size = payload_size + 9;
    output = encoded;
    return true;
}

bool StreamParser::push(const std::byte* data, std::size_t size) noexcept {
    if (size > kCapacity - size_ || (size != 0 && data == nullptr))
        return false;
    if (size != 0)
        std::memcpy(buffer_.data() + size_, data, size);
    size_ += size;
    return true;
}

bool StreamParser::pop(Packet& output) noexcept {
    std::size_t offset = 0;
    while (size_ - offset >= 2) {
        const auto* bytes = buffer_.data() + offset;
        const auto remaining = size_ - offset;
        if (bytes[0] != std::byte{0xff} || bytes[1] != std::byte{0xff}) {
            ++offset;
            continue;
        }
        if (remaining < 4)
            break;
        const auto body_size = static_cast<std::size_t>(read_be16(bytes + 2));
        if (body_size == 0 || body_size > kMaxPayload + 1) {
            ++offset;
            continue;
        }
        const auto wire_size = body_size + 8;
        if (remaining < wire_size)
            break;
        if (bytes[wire_size - 2] != std::byte{0x55} ||
            bytes[wire_size - 1] != std::byte{0xaa} ||
            read_be16(bytes + 4 + body_size) != crc16(bytes + 2, body_size + 2)) {
            ++offset;
            continue;
        }
        Packet decoded{};
        decoded.command = std::to_integer<std::uint8_t>(bytes[4]);
        decoded.payload_size = body_size - 1;
        std::copy_n(bytes + 5, decoded.payload_size, decoded.payload.begin());
        output = decoded;
        discard(offset + wire_size);
        return true;
    }
    // Preserve a possible split header but discard all other trailing noise.
    if (size_ - offset == 1 && buffer_[offset] != std::byte{0xff})
        ++offset;
    discard(offset);
    return false;
}

void StreamParser::discard(std::size_t count) noexcept {
    if (count == 0)
        return;
    size_ -= count;
    std::memmove(buffer_.data(), buffer_.data() + count, size_);
}
} // namespace rtctrl::patchx
