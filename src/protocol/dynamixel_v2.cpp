#include "rtctrl/protocol/dynamixel_v2.hpp"

#include <cstring>

namespace rtctrl::protocol {
namespace {

constexpr std::array<std::byte, 4> kHeader{std::byte{0xff}, std::byte{0xff}, std::byte{0xfd},
                                           std::byte{0x00}};

std::uint8_t value(std::byte input) noexcept {
    return static_cast<std::uint8_t>(input);
}

bool header_at(const std::byte* data) noexcept {
    return data[0] == kHeader[0] && data[1] == kHeader[1] && data[2] == kHeader[2] &&
           data[3] == kHeader[3];
}

} // namespace

std::uint16_t dynamixel_v2_crc16(const std::byte* data, std::size_t size) noexcept {
    if (data == nullptr && size != 0U) {
        return 0;
    }
    std::uint16_t crc = 0;
    for (std::size_t index = 0; index < size; ++index) {
        const auto high_byte =
            static_cast<std::uint16_t>(static_cast<unsigned int>(value(data[index])) * 256U);
        crc = static_cast<std::uint16_t>(crc ^ high_byte);
        for (unsigned int bit = 0; bit < 8U; ++bit) {
            crc = (crc & 0x8000U) != 0U ? static_cast<std::uint16_t>((crc << 1U) ^ 0x8005U)
                                        : static_cast<std::uint16_t>(crc << 1U);
        }
    }
    return crc;
}

bool encode_dynamixel_v2_packet(std::uint8_t id, std::uint8_t instruction,
                                const std::byte* parameters, std::size_t parameter_size,
                                std::byte* output, std::size_t capacity,
                                std::size_t& output_size) noexcept {
    output_size = 0;
    if (id > kDynamixelBroadcastId || output == nullptr ||
        (parameter_size != 0U && parameters == nullptr) ||
        parameter_size > kDynamixelV2MaxParameters || capacity < 10U) {
        return false;
    }

    std::memcpy(output, kHeader.data(), kHeader.size());
    output[4] = static_cast<std::byte>(id);
    std::size_t cursor = 7;
    output[cursor++] = static_cast<std::byte>(instruction);

    for (std::size_t index = 0; index < parameter_size; ++index) {
        if (cursor + 3U > capacity) {
            return false;
        }
        output[cursor++] = parameters[index];
        if (cursor >= 10U && output[cursor - 3U] == std::byte{0xff} &&
            output[cursor - 2U] == std::byte{0xff} && output[cursor - 1U] == std::byte{0xfd}) {
            output[cursor++] = std::byte{0xfd};
        }
    }

    const auto body_size = cursor - 7U;
    const auto length = body_size + 2U;
    if (length > 0xffffU || cursor + 2U > capacity) {
        return false;
    }
    output[5] = static_cast<std::byte>(length & 0xffU);
    output[6] = static_cast<std::byte>((length >> 8U) & 0xffU);
    const auto crc = dynamixel_v2_crc16(output, cursor);
    output[cursor++] = static_cast<std::byte>(crc & 0xffU);
    output[cursor++] = static_cast<std::byte>((crc >> 8U) & 0xffU);
    output_size = cursor;
    return true;
}

bool DynamixelV2StreamParser::push(const std::byte* data, std::size_t size) noexcept {
    if ((data == nullptr && size != 0U) || size > buffer_.size() - size_) {
        return false;
    }
    if (size != 0U) {
        std::memcpy(buffer_.data() + size_, data, size);
        size_ += size;
    }
    return true;
}

void DynamixelV2StreamParser::discard(std::size_t count) noexcept {
    if (count >= size_) {
        size_ = 0;
        return;
    }
    std::memmove(buffer_.data(), buffer_.data() + count, size_ - count);
    size_ -= count;
}

bool DynamixelV2StreamParser::pop(DynamixelV2Packet& packet) noexcept {
    while (size_ >= kHeader.size()) {
        std::size_t header = 0;
        while (header + kHeader.size() <= size_ && !header_at(buffer_.data() + header)) {
            ++header;
        }
        if (header != 0U) {
            discard(header);
        }
        if (size_ < 7U || !header_at(buffer_.data())) {
            return false;
        }

        const auto length = static_cast<std::size_t>(value(buffer_[5])) |
                            (static_cast<std::size_t>(value(buffer_[6])) << 8U);
        const auto total_size = 7U + length;
        if (length < 3U || total_size > kDynamixelV2MaxWirePacket) {
            discard(1);
            continue;
        }
        if (size_ < total_size) {
            return false;
        }
        const auto received_crc =
            static_cast<std::uint16_t>(value(buffer_[total_size - 2U])) |
            (static_cast<std::uint16_t>(value(buffer_[total_size - 1U])) << 8U);
        if (dynamixel_v2_crc16(buffer_.data(), total_size - 2U) != received_crc) {
            discard(1);
            continue;
        }

        std::array<std::byte, kDynamixelV2MaxParameters + 2U> body{};
        std::size_t body_size = 0;
        std::size_t cursor = 7;
        const auto body_end = total_size - 2U;
        while (cursor < body_end) {
            if (body_size == body.size()) {
                discard(total_size);
                return false;
            }
            body[body_size++] = buffer_[cursor++];
            if (body_size >= 3U && body[body_size - 3U] == std::byte{0xff} &&
                body[body_size - 2U] == std::byte{0xff} &&
                body[body_size - 1U] == std::byte{0xfd} && cursor < body_end &&
                buffer_[cursor] == std::byte{0xfd}) {
                ++cursor;
            }
        }
        if (body_size == 0U) {
            discard(total_size);
            continue;
        }

        packet = {};
        packet.id = value(buffer_[4]);
        packet.instruction = value(body[0]);
        std::size_t parameter_begin = 1;
        if (packet.instruction == kDynamixelStatusInstruction) {
            if (body_size < 2U) {
                discard(total_size);
                continue;
            }
            packet.error = value(body[1]);
            parameter_begin = 2;
        }
        packet.parameter_size = body_size - parameter_begin;
        if (packet.parameter_size > packet.parameters.size()) {
            discard(total_size);
            continue;
        }
        if (packet.parameter_size != 0U) {
            std::memcpy(packet.parameters.data(), body.data() + parameter_begin,
                        packet.parameter_size);
        }
        discard(total_size);
        return true;
    }
    return false;
}

} // namespace rtctrl::protocol
