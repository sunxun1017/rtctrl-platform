#include "rtctrl/transport/socketcan_fd_transport.hpp"

#include <chrono>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <thread>

int main() {
    const char* interface_name = std::getenv("RTCTRL_VCAN_INTERFACE");
    if (interface_name == nullptr || interface_name[0] == '\0') {
        std::cout << "SKIP: set RTCTRL_VCAN_INTERFACE=vcan0 to run SocketCAN loopback\n";
        return 0;
    }

    rtctrl::transport::SocketCanFdTransport receiver(interface_name);
    rtctrl::transport::SocketCanFdTransport sender(interface_name);
    const rtctrl::transport::CanFilter filter{0x123U, 0x7ffU, false};
    if (!receiver.set_filters(&filter, 1U) ||
        receiver.open() != rtctrl::transport::TransportStatus::Ok ||
        sender.open() != rtctrl::transport::TransportStatus::Ok) {
        std::cerr << "failed to open vcan interface: receiver=" << receiver.last_error()
                  << " sender=" << sender.last_error() << '\n';
        return 1;
    }

    rtctrl::transport::CanFrame sent{};
    sent.id = 0x123U;
    sent.fd = true;
    sent.bit_rate_switch = true;
    sent.size = 16U;
    for (std::size_t i = 0; i < sent.size; ++i) {
        sent.data[i] = static_cast<std::byte>(i + 1U);
    }
    const auto tx = sender.try_send(sent);
    if (tx.status != rtctrl::transport::TransportStatus::Ok) {
        std::cerr << "CAN-FD loopback send failed: " << tx.native_error << '\n';
        return 1;
    }

    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(250);
    rtctrl::transport::CanFrame received{};
    while (std::chrono::steady_clock::now() < deadline) {
        const auto rx = receiver.try_receive(received);
        if (rx.status == rtctrl::transport::TransportStatus::Ok) {
            if (received.id != sent.id || received.size != sent.size || !received.fd ||
                !received.bit_rate_switch ||
                std::memcmp(received.data.data(), sent.data.data(), sent.size) != 0) {
                std::cerr << "CAN-FD loopback payload or metadata mismatch\n";
                return 1;
            }
            std::cout << "SocketCAN CAN-FD vcan loopback passed\n";
            return 0;
        }
        if (rx.status != rtctrl::transport::TransportStatus::WouldBlock) {
            std::cerr << "CAN-FD loopback receive failed: " << rx.native_error << '\n';
            return 1;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    std::cerr << "CAN-FD loopback timed out\n";
    return 1;
}
