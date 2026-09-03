#include "rtctrl/transport/socketcan_fd_transport.hpp"

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <linux/can.h>
#include <linux/can/error.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

namespace rtctrl::transport {
namespace {

CanIoResult failed_result(int error) noexcept {
    if (error == EAGAIN || error == EWOULDBLOCK || error == EINTR) {
        return {TransportStatus::WouldBlock, error};
    }
    if (error == ENETDOWN || error == ENODEV || error == ENXIO) {
        return {TransportStatus::Closed, error};
    }
    return {TransportStatus::Error, error == 0 ? EIO : error};
}

canid_t encode_id(const CanFrame& frame) noexcept {
    canid_t id = frame.id;
    if (frame.extended) {
        id |= CAN_EFF_FLAG;
    }
    if (frame.remote_request) {
        id |= CAN_RTR_FLAG;
    }
    return id;
}

void decode_id(canid_t raw_id, CanFrame& frame) noexcept {
    frame.extended = (raw_id & CAN_EFF_FLAG) != 0U;
    frame.error_frame = (raw_id & CAN_ERR_FLAG) != 0U;
    frame.remote_request = !frame.error_frame && (raw_id & CAN_RTR_FLAG) != 0U;
    if (frame.error_frame) {
        // Error frames use the lower 29 bits as an error-class mask even though
        // CAN_EFF_FLAG is not set.
        frame.id = raw_id & CAN_ERR_MASK;
    } else {
        frame.id = raw_id & (frame.extended ? CAN_EFF_MASK : CAN_SFF_MASK);
    }
}

} // namespace

SocketCanFdTransport::SocketCanFdTransport(const char* interface_name,
                                           SocketCanFdConfig config) noexcept
    : config_(config) {
    if (interface_name == nullptr) {
        return;
    }
    const auto length = std::strlen(interface_name);
    if (length == 0 || length >= interface_name_.size()) {
        return;
    }
    std::memcpy(interface_name_.data(), interface_name, length + 1U);
    config_valid_ = true;
}

SocketCanFdTransport::~SocketCanFdTransport() {
    close();
}

bool SocketCanFdTransport::set_filters(const CanFilter* filters, std::size_t count) noexcept {
    if (fd_ >= 0 || count > filters_.size() || (count != 0U && filters == nullptr)) {
        last_error_ = EINVAL;
        return false;
    }
    for (std::size_t i = 0; i < count; ++i) {
        const auto id_mask = filters[i].extended ? CAN_EFF_MASK : CAN_SFF_MASK;
        if (filters[i].id > id_mask || filters[i].mask > id_mask) {
            last_error_ = EINVAL;
            return false;
        }
    }
    filter_count_ = count;
    for (std::size_t i = 0; i < count; ++i) {
        filters_[i] = filters[i];
    }
    last_error_ = 0;
    return true;
}

TransportStatus SocketCanFdTransport::open() noexcept {
    if (!config_valid_ || fd_ >= 0) {
        last_error_ = EINVAL;
        return TransportStatus::Error;
    }

    fd_ = ::socket(PF_CAN, SOCK_RAW | SOCK_NONBLOCK | SOCK_CLOEXEC, CAN_RAW);
    if (fd_ < 0) {
        last_error_ = errno;
        return TransportStatus::Error;
    }

    const int enabled = 1;
    const int loopback = config_.loopback ? 1 : 0;
    const int receive_own = config_.receive_own_messages ? 1 : 0;
    if (::setsockopt(fd_, SOL_CAN_RAW, CAN_RAW_FD_FRAMES, &enabled, sizeof(enabled)) != 0 ||
        ::setsockopt(fd_, SOL_CAN_RAW, CAN_RAW_LOOPBACK, &loopback, sizeof(loopback)) != 0 ||
        ::setsockopt(fd_, SOL_CAN_RAW, CAN_RAW_RECV_OWN_MSGS, &receive_own, sizeof(receive_own)) !=
            0) {
        last_error_ = errno;
        close();
        return TransportStatus::Error;
    }

    if (config_.receive_error_frames) {
        const can_err_mask_t error_mask = CAN_ERR_MASK;
        if (::setsockopt(fd_, SOL_CAN_RAW, CAN_RAW_ERR_FILTER, &error_mask, sizeof(error_mask)) !=
            0) {
            last_error_ = errno;
            close();
            return TransportStatus::Error;
        }
    }

    if (filter_count_ != 0U) {
        std::array<can_filter, kMaxFilters> native_filters{};
        for (std::size_t i = 0; i < filter_count_; ++i) {
            native_filters[i].can_id = filters_[i].id;
            native_filters[i].can_mask = filters_[i].mask | CAN_EFF_FLAG;
            if (filters_[i].extended) {
                native_filters[i].can_id |= CAN_EFF_FLAG;
            }
        }
        const auto bytes = static_cast<socklen_t>(filter_count_ * sizeof(can_filter));
        if (::setsockopt(fd_, SOL_CAN_RAW, CAN_RAW_FILTER, native_filters.data(), bytes) != 0) {
            last_error_ = errno;
            close();
            return TransportStatus::Error;
        }
    }

    if (config_.receive_timestamps &&
        ::setsockopt(fd_, SOL_SOCKET, SO_TIMESTAMPNS, &enabled, sizeof(enabled)) != 0) {
        last_error_ = errno;
        close();
        return TransportStatus::Error;
    }

    const unsigned int interface_index = ::if_nametoindex(interface_name_.data());
    if (interface_index == 0U) {
        last_error_ = errno == 0 ? ENODEV : errno;
        close();
        return TransportStatus::Error;
    }
    sockaddr_can address{};
    address.can_family = AF_CAN;
    address.can_ifindex = static_cast<int>(interface_index);
    if (::bind(fd_, reinterpret_cast<const sockaddr*>(&address), sizeof(address)) != 0) {
        last_error_ = errno;
        close();
        return TransportStatus::Error;
    }

    last_error_ = 0;
    return TransportStatus::Ok;
}

CanIoResult SocketCanFdTransport::try_receive(CanFrame& output) noexcept {
    if (fd_ < 0) {
        last_error_ = ENOTCONN;
        return {TransportStatus::Closed, ENOTCONN};
    }

    canfd_frame native{};
    alignas(cmsghdr) std::array<std::byte, CMSG_SPACE(sizeof(timespec))> control{};
    iovec io{&native, sizeof(native)};
    msghdr message{};
    message.msg_iov = &io;
    message.msg_iovlen = 1;
    message.msg_control = control.data();
    message.msg_controllen = control.size();
    const ssize_t received = ::recvmsg(fd_, &message, MSG_DONTWAIT);
    if (received < 0) {
        last_error_ = errno;
        return failed_result(last_error_);
    }
    if (received != CAN_MTU && received != CANFD_MTU) {
        last_error_ = EPROTO;
        return {TransportStatus::Error, EPROTO};
    }

    CanFrame next{};
    next.fd = received == CANFD_MTU;
    decode_id(native.can_id, next);
    next.size = native.len;
    if (next.size > kCanFdMaxPayload || (!next.fd && next.size > 8U)) {
        last_error_ = EPROTO;
        return {TransportStatus::Error, EPROTO};
    }
    if (next.fd) {
        next.bit_rate_switch = (native.flags & CANFD_BRS) != 0U;
        next.error_state_indicator = (native.flags & CANFD_ESI) != 0U;
    }
    std::memcpy(next.data.data(), native.data, next.size);

    for (cmsghdr* header = CMSG_FIRSTHDR(&message); header != nullptr;
         header = CMSG_NXTHDR(&message, header)) {
        if (header->cmsg_level == SOL_SOCKET && header->cmsg_type == SCM_TIMESTAMPNS &&
            header->cmsg_len >= CMSG_LEN(sizeof(timespec))) {
            timespec timestamp{};
            std::memcpy(&timestamp, CMSG_DATA(header), sizeof(timestamp));
            next.timestamp_ns =
                static_cast<std::int64_t>(timestamp.tv_sec) * 1'000'000'000LL + timestamp.tv_nsec;
            break;
        }
    }
    output = next;
    last_error_ = 0;
    return {TransportStatus::Ok, 0};
}

CanIoResult SocketCanFdTransport::try_send(const CanFrame& input) noexcept {
    if (fd_ < 0) {
        last_error_ = ENOTCONN;
        return {TransportStatus::Closed, ENOTCONN};
    }
    if (!valid_can_frame(input, true)) {
        last_error_ = EINVAL;
        return {TransportStatus::Error, EINVAL};
    }

    ssize_t sent = -1;
    if (input.fd) {
        canfd_frame native{};
        native.can_id = encode_id(input);
        native.len = input.size;
        native.flags = static_cast<__u8>((input.bit_rate_switch ? CANFD_BRS : 0U) |
                                         (input.error_state_indicator ? CANFD_ESI : 0U));
        std::memcpy(native.data, input.data.data(), input.size);
        sent = ::send(fd_, &native, CANFD_MTU, MSG_DONTWAIT);
        if (sent >= 0 && sent != CANFD_MTU) {
            last_error_ = EIO;
            return {TransportStatus::Error, EIO};
        }
    } else {
        can_frame native{};
        native.can_id = encode_id(input);
        native.can_dlc = input.size;
        std::memcpy(native.data, input.data.data(), input.size);
        sent = ::send(fd_, &native, CAN_MTU, MSG_DONTWAIT);
        if (sent >= 0 && sent != CAN_MTU) {
            last_error_ = EIO;
            return {TransportStatus::Error, EIO};
        }
    }
    if (sent < 0) {
        last_error_ = errno;
        return failed_result(last_error_);
    }
    last_error_ = 0;
    return {TransportStatus::Ok, 0};
}

void SocketCanFdTransport::close() noexcept {
    if (fd_ >= 0) {
        (void)::close(fd_);
        fd_ = -1;
    }
}

} // namespace rtctrl::transport
