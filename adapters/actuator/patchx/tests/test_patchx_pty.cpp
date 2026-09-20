#include "rtctrl/adapters/patchx/patchx_codec.hpp"
#include "rtctrl/adapters/serial/posix_serial_transport.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cstdlib>
#include <fcntl.h>
#include <iostream>
#include <poll.h>
#include <thread>
#include <unistd.h>

namespace {
using B = std::byte;
using rtctrl::transport::TransportStatus;
using Clock = std::chrono::steady_clock;
constexpr std::array<B, 11> fixture{B{0xff},
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

bool check(bool ok, const char* message) {
    if (!ok)
        std::cerr << "FAIL: " << message << '\n';
    return ok;
}

class Pty final {
  public:
    int fd{::posix_openpt(O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC)};
    ~Pty() {
        close();
    }
    void close() {
        if (fd >= 0)
            (void)::close(fd);
        fd = -1;
    }
};

bool read_master(int fd, B* data, std::size_t size) {
    const auto deadline = Clock::now() + std::chrono::seconds(1);
    std::size_t used = 0;
    while (used < size && Clock::now() < deadline) {
        pollfd ready{fd, POLLIN, 0};
        const int result = ::poll(&ready, 1, 10);
        if (result < 0 && errno != EINTR)
            return false;
        if (result <= 0)
            continue;
        const auto count = ::read(fd, data + used, size - used);
        if (count < 0 && (errno == EAGAIN || errno == EINTR))
            continue;
        if (count <= 0)
            return false;
        used += static_cast<std::size_t>(count);
    }
    return used == size;
}

bool read_serial(rtctrl::transport::IByteTransport& serial,
                 B* data,
                 std::size_t size) {
    const auto deadline = Clock::now() + std::chrono::seconds(1);
    std::size_t used = 0;
    while (used < size && Clock::now() < deadline) {
        const auto result = serial.try_receive(data + used, size - used);
        if (result.status == TransportStatus::WouldBlock) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
            continue;
        }
        if (result.status != TransportStatus::Ok || result.bytes == 0 ||
            result.bytes > size - used)
            return false;
        used += result.bytes;
    }
    return used == size;
}

bool run() {
    // Only a kernel-created pseudo-terminal is ever opened. No configurable
    // tty path and no hardware/motor commands can leave this isolated pair.
    Pty master;
    if (!check(master.fd >= 0 && ::grantpt(master.fd) == 0 &&
                   ::unlockpt(master.fd) == 0,
               "create actual POSIX pseudo-terminal (failure is not a silent skip)"))
        return false;
    const char* slave = ::ptsname(master.fd);
    if (!check(slave != nullptr, "resolve generated slave path"))
        return false;
    rtctrl::transport::PosixSerialTransport transport(slave, 115200);
    rtctrl::transport::IByteTransport& serial = transport;
    if (!check(serial.open() == TransportStatus::Ok,
               "open real Linux serial adapter on PTY"))
        return false;
    pollfd outgoing{master.fd, POLLIN, 0};
    if (!check(::poll(&outgoing, 1, 20) == 0,
               "opening the transport sends no bytes"))
        return false;
    B scratch{};
    if (!check(serial.try_receive(&scratch, 1).status == TransportStatus::WouldBlock,
               "idle open tty is WouldBlock, not a disconnected device"))
        return false;

    rtctrl::patchx::WireFrame encoded{};
    if (!check(rtctrl::patchx::encode_frame(0xfa, fixture.data() + 5, 2, encoded),
               "encode fixture for application-to-PTY direction"))
        return false;
    std::size_t sent = 0;
    while (sent < encoded.size) {
        const auto io =
            serial.try_send(encoded.bytes.data() + sent, encoded.size - sent);
        if (!check(io.status == TransportStatus::Ok && io.bytes > 0 &&
                       io.bytes <= encoded.size - sent,
                   "send small frame to PTY master"))
            return false;
        sent += io.bytes;
    }
    std::array<B, fixture.size()> observed{};
    if (!check(read_master(master.fd, observed.data(), observed.size()) &&
                   observed == fixture,
               "raw serial TX preserves exact independently known frame"))
        return false;

    rtctrl::patchx::StreamParser parser;
    rtctrl::patchx::Packet packet{};
    for (std::size_t i = 0; i < fixture.size(); ++i) {
        if (!check(::write(master.fd, fixture.data() + i, 1) == 1 &&
                       read_serial(serial, &scratch, 1) && parser.push(&scratch, 1),
                   "one-byte fragments pass through the actual tty receive path"))
            return false;
        if (!check(parser.pop(packet) == (i + 1 == fixture.size()),
                   "decode only once the final fragment arrives"))
            return false;
    }
    if (!check(packet.command == 0xfa && packet.payload_size == 2 &&
                   packet.payload[0] == B{0x12} && packet.payload[1] == B{0x34},
               "injected RX fixture retains raw command and payload"))
        return false;
    if (!check(serial.try_receive(&scratch, 1).status == TransportStatus::WouldBlock,
               "drained tty remains open and idle"))
        return false;

    std::array<B, fixture.size() * 2> mixed{};
    std::copy(fixture.begin(), fixture.end(), mixed.begin());
    mixed[7] ^= B{1};
    std::copy(fixture.begin(), fixture.end(), mixed.begin() + fixture.size());
    if (!check(::write(master.fd, mixed.data(), mixed.size()) ==
                   static_cast<ssize_t>(mixed.size()),
               "inject corrupt frame and complete successor in one write"))
        return false;
    std::array<B, 3> chunk{};
    int frames = 0;
    for (std::size_t remaining = mixed.size(); remaining != 0;) {
        const auto count = std::min(remaining, chunk.size());
        if (!check(read_serial(serial, chunk.data(), count) &&
                       parser.push(chunk.data(), count),
                   "bounded receive chunks reassemble coalesced input"))
            return false;
        while (parser.pop(packet))
            ++frames;
        remaining -= count;
    }
    if (!check(frames == 1 && packet.command == 0xfa,
               "bad CRC is discarded and following frame recovers through real "
               "serial adapter"))
        return false;

    if (!check(parser.push(fixture.data(), 6),
               "retain a partial old-generation frame"))
        return false;
    serial.close();
    if (!check(serial.try_receive(&scratch, 1).status == TransportStatus::Closed &&
                   serial.try_send(&scratch, 1).status == TransportStatus::Closed,
               "explicit close revokes both I/O directions"))
        return false;
    parser.reset();
    if (!check(serial.open() == TransportStatus::Ok && !parser.pop(packet) &&
                   serial.try_receive(&scratch, 1).status ==
                       TransportStatus::WouldBlock,
               "reopen plus parser reset begins an empty new session"))
        return false;
    master.close();
    const auto disconnected = serial.try_receive(&scratch, 1).status;
    if (!check(disconnected == TransportStatus::Closed ||
                   disconnected == TransportStatus::Error,
               "actual PTY hangup is not reported as idle"))
        return false;
    serial.close();
    return true;
}
} // namespace

int main() {
    if (!run())
        return EXIT_FAILURE;
    std::cout << "PatchX POSIX PTY: idle, exact TX, fragmented RX, corruption, "
                 "reopen and hangup passed\n";
    return EXIT_SUCCESS;
}
