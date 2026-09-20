#include "rtctrl/adapters/loopback/loopback_byte_transport.hpp"
#include "rtctrl/adapters/patchx/patchx_codec.hpp"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <iostream>

namespace {
using namespace rtctrl::patchx;
using B = std::byte;
int failures = 0;
void expect(bool ok, const char* message) {
    if (!ok) {
        ++failures;
        std::cerr << "FAIL: " << message << '\n';
    }
}

// Independently checked against the Android sender's CRC formula, including
// its unusual high-byte-first Modbus CRC. These are not encoder round trips.
constexpr std::array<B, 9> action{
    B{0xff}, B{0xff}, B{0}, B{1}, B{1}, B{0x90}, B{0xb1}, B{0x55}, B{0xaa}};
constexpr std::array<B, 11> angle{B{0xff},
                                  B{0xff},
                                  B{0},
                                  B{3},
                                  B{0xfa},
                                  B{0x12},
                                  B{0x34},
                                  B{0x02},
                                  B{0x09},
                                  B{0x55},
                                  B{0xaa}};
constexpr std::array<B, 17> upgrade{B{0xff},
                                    B{0xff},
                                    B{0},
                                    B{9},
                                    B{0xdf},
                                    B{0},
                                    B{1},
                                    B{0},
                                    B{4},
                                    B{0},
                                    B{1},
                                    B{0xfe},
                                    B{0xff},
                                    B{0x1e},
                                    B{0xba},
                                    B{0x55},
                                    B{0xaa}};
// 7E is arbitrary raw data, not a claimed device command.
constexpr std::array<B, 14> embedded{B{0xff},
                                     B{0xff},
                                     B{0},
                                     B{6},
                                     B{0x7e},
                                     B{0xff},
                                     B{0xff},
                                     B{0x55},
                                     B{0xaa},
                                     B{0},
                                     B{0xa5},
                                     B{0x66},
                                     B{0x55},
                                     B{0xaa}};

template <std::size_t N> void check_encoding(const std::array<B, N>& fixture) {
    WireFrame frame{};
    const auto payload_size = N - 9;
    expect(encode_frame(std::to_integer<std::uint8_t>(fixture[4]),
                        payload_size ? fixture.data() + 5 : nullptr,
                        payload_size,
                        frame),
           "known Android command encodes");
    expect(frame.size == fixture.size() &&
               std::equal(fixture.begin(), fixture.end(), frame.bytes.begin()),
           "length, byte order, CRC and trailer match independent fixture");
}

template <std::size_t N>
void check_packet(const Packet& packet, const std::array<B, N>& fixture) {
    expect(packet.command == std::to_integer<std::uint8_t>(fixture[4]) &&
               packet.payload_size == N - 9 &&
               std::equal(
                   fixture.begin() + 5, fixture.end() - 4, packet.payload.begin()),
           "parser returns exact command and payload");
}

void test_vectors_and_fragmentation() {
    check_encoding(action);
    check_encoding(angle);
    check_encoding(upgrade);
    check_encoding(embedded);
    StreamParser markers;
    Packet decoded{};
    expect(markers.push(embedded.data(), embedded.size()) && markers.pop(decoded),
           "independent vector accepts delimiters inside payload");
    check_packet(decoded, embedded);
    WireFrame aliased{};
    aliased.bytes[0] = B{0x12};
    aliased.bytes[1] = B{0x34};
    expect(encode_frame(0xfa, aliased.bytes.data(), 2, aliased) &&
               aliased.size == angle.size() &&
               std::equal(angle.begin(), angle.end(), aliased.bytes.begin()),
           "encoding can reuse previous output bytes as input payload");
    for (std::size_t split = 0; split <= angle.size(); ++split) {
        StreamParser parser;
        Packet packet{};
        packet.command = 0x80;
        expect(parser.push(angle.data(), split), "accept every initial fragment");
        if (split < angle.size()) {
            expect(!parser.pop(packet) && packet.command == 0x80,
                   "partial input produces no packet and preserves output");
        }
        expect(parser.push(angle.data() + split, angle.size() - split),
               "accept final fragment");
        expect(parser.pop(packet), "every split reassembles");
        check_packet(packet, angle);
        expect(!parser.pop(packet), "packet delivered exactly once");
    }
}

void test_corruption_and_resync() {
    // Length, command, data, CRC and trailer corruption must not escape as a
    // valid packet. Change length to zero/too large separately below.
    for (std::size_t index = 4; index < angle.size(); ++index) {
        auto bad = angle;
        bad[index] ^= B{1};
        StreamParser parser;
        Packet packet{};
        expect(parser.push(bad.data(), bad.size()),
               "accept corrupt input for validation");
        expect(!parser.pop(packet), "reject mutated command/payload/CRC/trailer");
        expect(parser.push(action.data(), action.size()) && parser.pop(packet),
               "recover after corrupt frame");
        check_packet(packet, action);
    }
    const std::array<B, 16> noise{B{0},
                                  B{0x55},
                                  B{0xaa},
                                  B{0xff},
                                  B{0xff},
                                  B{0},
                                  B{0},
                                  B{0x10},
                                  B{0xff},
                                  B{0xff},
                                  B{1},
                                  B{6},
                                  B{0x10},
                                  B{0x11},
                                  B{0x12},
                                  B{0x13}};
    StreamParser parser;
    Packet packet{};
    expect(parser.push(noise.data(), noise.size()) &&
               parser.push(action.data(), action.size()) &&
               parser.push(angle.data(), angle.size()) && parser.pop(packet),
           "skip noise, zero body and over-limit body lengths");
    check_packet(packet, action);
    expect(parser.pop(packet), "coalesced second frame is retained");
    check_packet(packet, angle);
    expect(!parser.pop(packet), "noise never becomes another frame");
    auto swapped_crc = action;
    std::swap(swapped_crc[5], swapped_crc[6]);
    expect(parser.push(swapped_crc.data(), swapped_crc.size()) &&
               !parser.pop(packet),
           "reject conventional little-endian Modbus CRC on PatchX wire");
    const std::array<B, 5> weak_ack{B{0}, B{0}, B{0}, B{0}, B{0xde}};
    expect(parser.push(weak_ack.data(), weak_ack.size()) && !parser.pop(packet),
           "command in fifth byte alone is not a valid frame");
}

void test_capacity_reset_and_embedded_markers() {
    std::array<B, kMaxPayload + 1> data{};
    WireFrame frame{};
    expect(!encode_frame(1, data.data(), data.size(), frame) && frame.size == 0,
           "oversize payload is rejected without a truncated frame");
    expect(!encode_frame(1, nullptr, 1, frame) && frame.size == 0,
           "nonempty null payload is rejected");
    data.fill(B{0xff});
    data[17] = B{0x55};
    data[18] = B{0xaa};
    expect(encode_frame(0xdf, data.data(), kMaxPayload, frame) &&
               frame.size == kMaxWireFrame && frame.bytes[2] == B{1} &&
               frame.bytes[3] == B{5},
           "maximum local capacity uses a full big-endian 16-bit body length");
    StreamParser parser;
    Packet packet{};
    expect(parser.push(frame.bytes.data(), frame.size) &&
               parser.push(frame.bytes.data(), frame.size),
           "buffer holds two maximum-size frames");
    expect(!parser.push(action.data(), action.size()) &&
               parser.buffered_size() == StreamParser::kCapacity,
           "overflow is atomic and preserves pending data");
    expect(parser.pop(packet) && packet.payload_size == kMaxPayload &&
               std::equal(
                   data.begin(), data.begin() + kMaxPayload, packet.payload.begin()),
           "embedded headers/trailers do not split a valid payload");
    expect(parser.pop(packet) && !parser.pop(packet),
           "both maximum frames drain exactly once");
    expect(parser.push(nullptr, 0) && !parser.push(nullptr, 1),
           "null input is legal only when empty");
    expect(parser.push(action.data(), 6),
           "accept truncated frame before disconnect");
    parser.reset();
    expect(parser.buffered_size() == 0 && !parser.pop(packet),
           "reconnect reset discards old fragment");
    expect(parser.push(action.data(), action.size()) && parser.pop(packet),
           "fresh frame works after reset");
    check_packet(packet, action);
    // A plausible but incomplete body can contain an entire valid-looking
    // frame. It must wait for the caller's timeout, not split payload early.
    parser.reset();
    const std::array<B, 4> pending{B{0xff}, B{0xff}, B{0}, B{0xff}};
    expect(parser.push(pending.data(), pending.size()) &&
               parser.push(action.data(), action.size()) && !parser.pop(packet),
           "plausible incomplete length waits for an explicit timeout");
    parser.reset();
    expect(parser.push(action.data(), action.size()) && parser.pop(packet),
           "deadline reset recovers from plausible corrupt length");
    frame.size = 99;
    expect(!encode_frame(1, nullptr, 3, frame) && frame.size == 0,
           "failure revokes previous output size");
}

void test_transport_short_reads() {
    using namespace rtctrl::transport;
    LoopbackByteTransport transport(1);
    IByteTransport& link = transport;
    expect(link.open() == TransportStatus::Ok, "open in-memory byte transport");
    expect(transport.inject(upgrade.data(), upgrade.size()),
           "inject literal wire fixture");
    StreamParser parser;
    Packet packet{};
    std::array<B, 32> chunk{};
    for (std::size_t i = 0; i < upgrade.size(); ++i) {
        const auto io = link.try_receive(chunk.data(), chunk.size());
        expect(io.status == TransportStatus::Ok && io.bytes == 1,
               "transport returns one-byte fragment");
        expect(parser.push(chunk.data(), io.bytes),
               "parser accepts transport fragment");
        expect(parser.pop(packet) == (i + 1 == upgrade.size()),
               "deliver only after final transport byte");
    }
    check_packet(packet, upgrade);
    expect(link.try_receive(chunk.data(), chunk.size()).status ==
               TransportStatus::WouldBlock,
           "parser integration does not require blocking receive");
    link.close();
}
} // namespace

int main() {
    test_vectors_and_fragmentation();
    test_corruption_and_resync();
    test_capacity_reset_and_embedded_markers();
    test_transport_short_reads();
    if (failures != 0)
        return EXIT_FAILURE;
    std::cout << "PatchX codec: vectors, fragmentation, corruption, bounds and byte "
                 "transport passed\n";
    return EXIT_SUCCESS;
}
