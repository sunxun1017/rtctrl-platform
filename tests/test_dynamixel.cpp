#include "rtctrl/hal/dynamixel_protocol.hpp"
#include "rtctrl/hal/half_duplex_serial_link.hpp"
#include "rtctrl/protocol/dynamixel_v2.hpp"
#include "rtctrl/transport/posix_serial_transport.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <unistd.h>

namespace {

int failures = 0;

void expect(bool condition, const char* message) {
    if (!condition) {
        ++failures;
        std::cerr << "FAIL: " << message << '\n';
    }
}

void put_i32(std::byte* output, std::int32_t value) {
    const auto raw = static_cast<std::uint32_t>(value);
    for (unsigned int index = 0; index < 4U; ++index) {
        output[index] = static_cast<std::byte>((raw >> (8U * index)) & 0xffU);
    }
}

void put_i16(std::byte* output, std::int16_t value) {
    const auto raw = static_cast<std::uint16_t>(value);
    output[0] = static_cast<std::byte>(raw & 0xffU);
    output[1] = static_cast<std::byte>((raw >> 8U) & 0xffU);
}

void test_official_sync_read_vector() {
    using namespace rtctrl::protocol;
    const std::array<std::byte, 6> parameters{std::byte{0x84}, std::byte{0x00}, std::byte{0x04},
                                              std::byte{0x00}, std::byte{0x01}, std::byte{0x02}};
    std::array<std::byte, 32> encoded{};
    std::size_t encoded_size = 0;
    expect(encode_dynamixel_v2_packet(
               kDynamixelBroadcastId, static_cast<std::uint8_t>(DynamixelV2Instruction::SyncRead),
               parameters.data(), parameters.size(), encoded.data(), encoded.size(), encoded_size),
           "official Protocol 2.0 Sync Read vector encodes");
    expect(encoded_size == 16U && encoded[14] == std::byte{0xce} && encoded[15] == std::byte{0xfa},
           "Protocol 2.0 CRC matches the official CE FA example");

    DynamixelV2StreamParser parser;
    DynamixelV2Packet partial{};
    expect(parser.push(encoded.data(), 5) && !parser.pop(partial),
           "partial Dynamixel packet waits for remaining bytes");
    expect(parser.push(encoded.data() + 5, encoded_size - 5),
           "remaining Dynamixel bytes are accepted");
    DynamixelV2Packet packet{};
    expect(parser.pop(packet) && packet.id == kDynamixelBroadcastId &&
               packet.instruction == 0x82U && packet.parameter_size == parameters.size(),
           "stream parser reconstructs a split instruction packet");
}

void test_stuffing_and_crc_recovery() {
    using namespace rtctrl::protocol;
    const std::array<std::byte, 5> parameters{std::byte{0x11}, std::byte{0xff}, std::byte{0xff},
                                              std::byte{0xfd}, std::byte{0x22}};
    std::array<std::byte, 64> encoded{};
    std::size_t encoded_size = 0;
    expect(encode_dynamixel_v2_packet(1, 0x03, parameters.data(), parameters.size(), encoded.data(),
                                      encoded.size(), encoded_size),
           "byte-stuffed packet encodes");
    expect(encoded_size == 16U, "FF FF FD payload pattern adds exactly one stuffed byte");
    DynamixelV2StreamParser parser;
    const std::array<std::byte, 3> garbage{std::byte{0x00}, std::byte{0x7f}, std::byte{0xff}};
    expect(parser.push(garbage.data(), garbage.size()) && parser.push(encoded.data(), encoded_size),
           "parser accepts garbage-prefixed packet");
    DynamixelV2Packet packet{};
    expect(parser.pop(packet) && packet.parameter_size == parameters.size() &&
               std::memcmp(packet.parameters.data(), parameters.data(), parameters.size()) == 0,
           "parser removes byte stuffing and resynchronizes after garbage");

    encoded[encoded_size - 1U] ^= std::byte{0x01};
    expect(parser.push(encoded.data(), encoded_size) && !parser.pop(packet),
           "parser rejects a corrupted CRC");

    std::array<std::byte, 180> worst_case{};
    for (std::size_t index = 0; index < worst_case.size(); index += 3U) {
        worst_case[index] = std::byte{0xff};
        worst_case[index + 1U] = std::byte{0xff};
        worst_case[index + 2U] = std::byte{0xfd};
    }
    std::array<std::byte, rtctrl::hal::kActuatorPacketPayloadCapacity> bounded_wire{};
    expect(encode_dynamixel_v2_packet(1, 0x03, worst_case.data(), worst_case.size(),
                                      bounded_wire.data(), bounded_wire.size(), encoded_size) &&
               encoded_size <= bounded_wire.size(),
           "worst-case stuffing remains inside the actuator packet bound");
}

std::array<rtctrl::hal::DynamixelJointProfile, rtctrl::model::kJointCount> make_profiles() {
    std::array<rtctrl::hal::DynamixelJointProfile, rtctrl::model::kJointCount> profiles{};
    for (std::size_t index = 0; index < profiles.size(); ++index) {
        profiles[index].id = static_cast<std::uint8_t>(index + 1U);
        profiles[index].torque_enable = {64, 1};
        profiles[index].goal_position = {116, 4};
        profiles[index].present_effort = {126, 2};
        profiles[index].present_velocity = {128, 4};
        profiles[index].present_position = {132, 4};
        profiles[index].position_zero_raw = 2048;
        profiles[index].position_rad_per_unit = 0.001;
        profiles[index].velocity_rad_s_per_unit = 0.01;
        profiles[index].effort_nm_per_unit = 0.1;
    }
    return profiles;
}

void test_motor_protocol_profile() {
    using namespace rtctrl::hal;
    auto profiles = make_profiles();
    const DynamixelProtocolConfig config{profiles.data(), profiles.size()};
    expect(valid_dynamixel_protocol_config(config),
           "model-independent Dynamixel control-table profile validates");
    DynamixelProtocol2 protocol(config);
    expect(protocol.valid(), "Dynamixel protocol accepts the profile");

    ActuatorPacketBatch outgoing;
    const auto bulk_request_count = (profiles.size() + 35U) / 36U;
    const auto position_write_count = (profiles.size() + 34U) / 35U;
    expect(protocol.encode_startup(0, outgoing) == ActuatorProtocolStatus::Ok &&
               outgoing.size() == bulk_request_count,
           "startup emits bounded batched Bulk Read requests");
    rtctrl::protocol::DynamixelV2StreamParser request_parser;
    expect(request_parser.push(outgoing[0].payload.data(), outgoing[0].size),
           "Bulk Read wire packet enters parser");
    rtctrl::protocol::DynamixelV2Packet request{};
    expect(request_parser.pop(request) && request.instruction == 0x92U &&
               request.parameter_size == std::min<std::size_t>(profiles.size(), 36U) * 5U,
           "startup request uses Protocol 2.0 Bulk Read layout");

    ActuatorPacketBatch incoming;
    for (std::size_t index = 0; index < profiles.size(); ++index) {
        std::array<std::byte, 11> status_parameters{};
        status_parameters[0] = std::byte{0x00};
        put_i16(status_parameters.data() + 1, static_cast<std::int16_t>(index + 1));
        put_i32(status_parameters.data() + 3, static_cast<std::int32_t>(index + 2));
        put_i32(status_parameters.data() + 7, static_cast<std::int32_t>(2048 + index * 10));
        ActuatorPacket wire{};
        std::size_t wire_size = 0;
        expect(rtctrl::protocol::encode_dynamixel_v2_packet(
                   profiles[index].id, rtctrl::protocol::kDynamixelStatusInstruction,
                   status_parameters.data(), status_parameters.size(), wire.payload.data(),
                   wire.payload.size(), wire_size),
               "status packet encodes");
        wire.size = static_cast<std::uint16_t>(wire_size);
        expect(incoming.push(wire), "status packet enters fixed batch");
    }
    rtctrl::model::SensorFrame feedback{};
    expect(protocol.decode_feedback(1234, incoming, feedback) == ActuatorProtocolStatus::Ok &&
               feedback.sequence == 1U && feedback.sample_time_ns == 1234,
           "all ID status packets complete one feedback frame");
    expect(std::abs(feedback.position[1] - 0.01) < 1e-12 &&
               std::abs(feedback.velocity[1] - 0.03) < 1e-12 &&
               std::abs(feedback.effort[1] - 0.2) < 1e-12,
           "profile converts raw position, velocity and effort to SI units");

    expect(protocol.encode_arm(0, outgoing) == ActuatorProtocolStatus::Ok &&
               outgoing.size() == 1U + bulk_request_count,
           "arm batches Torque Enable and the next Bulk Read");
    rtctrl::model::CommandFrame command{};
    command.mode = rtctrl::model::CommandMode::Position;
    command.target_position.fill(0.1);
    expect(protocol.encode_command(0, command, outgoing) == ActuatorProtocolStatus::Ok &&
               outgoing.size() == position_write_count + bulk_request_count,
           "position command batches Sync Write and the next Bulk Read");
    expect(protocol.encode_safe_stop(0, outgoing) == ActuatorProtocolStatus::Ok &&
               outgoing.size() == 1U,
           "safe stop broadcasts a batched Torque Disable");

    profiles[1].id = profiles[0].id;
    expect(!valid_dynamixel_protocol_config({profiles.data(), profiles.size()}),
           "duplicate bus IDs are rejected before opening serial hardware");
}

class PartialByteTransport final : public rtctrl::transport::IByteTransport {
  public:
    rtctrl::transport::TransportStatus open() noexcept override {
        open_ = true;
        return rtctrl::transport::TransportStatus::Ok;
    }
    rtctrl::transport::IoResult try_receive(std::byte* destination,
                                            std::size_t capacity) noexcept override {
        if (!open_) {
            return {rtctrl::transport::TransportStatus::Closed, 0, 0};
        }
        if (receive_size_ == 0U) {
            return {rtctrl::transport::TransportStatus::WouldBlock, 0, 0};
        }
        const auto count = std::min(capacity, receive_size_);
        std::memcpy(destination, receive_.data(), count);
        receive_size_ = 0;
        return {rtctrl::transport::TransportStatus::Ok, count, 0};
    }
    rtctrl::transport::IoResult try_send(const std::byte* source,
                                         std::size_t size) noexcept override {
        if (!open_) {
            return {rtctrl::transport::TransportStatus::Closed, 0, 0};
        }
        const auto count = std::min<std::size_t>(size, 3);
        std::memcpy(sent_.data() + sent_size_, source, count);
        sent_size_ += count;
        return {rtctrl::transport::TransportStatus::Ok, count, 0};
    }
    void close() noexcept override {
        open_ = false;
    }

    std::array<std::byte, 32> receive_{};
    std::size_t receive_size_{0};
    std::array<std::byte, 128> sent_{};
    std::size_t sent_size_{0};

  private:
    bool open_{false};
};

void test_half_duplex_partial_io() {
    using namespace rtctrl::hal;
    PartialByteTransport bytes;
    HalfDuplexSerialLink link(bytes);
    expect(link.open() == ActuatorLinkStatus::Ok,
           "half-duplex link opens its injected byte transport");
    ActuatorPacket packet{};
    packet.size = 8;
    for (std::size_t index = 0; index < packet.size; ++index) {
        packet.payload[index] = static_cast<std::byte>(index);
    }
    ActuatorPacketBatch outgoing;
    expect(outgoing.push(packet) && link.transmit(0, outgoing) == ActuatorLinkStatus::Ok,
           "partial serial write is retained in a fixed internal queue");
    ActuatorPacketBatch incoming;
    expect(link.receive(1, incoming) == ActuatorLinkStatus::WouldBlock &&
               link.receive(2, incoming) == ActuatorLinkStatus::WouldBlock,
           "receive phase first drains the half-duplex transmit queue");
    bytes.receive_[0] = std::byte{0xaa};
    bytes.receive_size_ = 1;
    expect(link.receive(3, incoming) == ActuatorLinkStatus::Ok && incoming.size() == 1U &&
               incoming[0].payload[0] == std::byte{0xaa} && bytes.sent_size_ == 8U,
           "link changes to receive only after the full packet is accepted");
    link.close();
}

void test_posix_one_megabaud() {
    const int master = ::posix_openpt(O_RDWR | O_NOCTTY);
    if (master < 0 || ::grantpt(master) != 0 || ::unlockpt(master) != 0) {
        if (master >= 0) {
            (void)::close(master);
        }
        std::cout << "SKIP: pseudo-terminal unavailable for 1 Mbps test\n";
        return;
    }
    const char* slave = ::ptsname(master);
    expect(slave != nullptr, "pseudo-terminal exposes a slave path");
    if (slave != nullptr) {
        rtctrl::transport::PosixSerialTransport serial(slave, 1'000'000);
        expect(serial.open() == rtctrl::transport::TransportStatus::Ok,
               "POSIX serial accepts the exact Dynamixel 1 Mbps baud rate");
        serial.close();
    }
    (void)::close(master);
}

} // namespace

int main() {
    test_official_sync_read_vector();
    test_stuffing_and_crc_recovery();
    test_motor_protocol_profile();
    test_half_duplex_partial_io();
    test_posix_one_megabaud();
    if (failures == 0) {
        std::cout << "Dynamixel Protocol 2.0 tests passed\n";
    }
    return failures == 0 ? 0 : 1;
}
