#include "rtctrl/transport/posix_serial_transport.hpp"

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <linux/serial.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>

namespace rtctrl::transport {
namespace {

speed_t to_speed(int baud_rate) noexcept {
  switch (baud_rate) {
    case 9600: return B9600;
    case 19200: return B19200;
    case 38400: return B38400;
    case 57600: return B57600;
    case 115200: return B115200;
#ifdef B230400
    case 230400: return B230400;
#endif
#ifdef B460800
    case 460800: return B460800;
#endif
#ifdef B500000
    case 500000: return B500000;
#endif
#ifdef B576000
    case 576000: return B576000;
#endif
#ifdef B921600
    case 921600: return B921600;
#endif
#ifdef B1000000
    case 1000000: return B1000000;
#endif
#ifdef B1152000
    case 1152000: return B1152000;
#endif
#ifdef B1500000
    case 1500000: return B1500000;
#endif
#ifdef B2000000
    case 2000000: return B2000000;
#endif
#ifdef B2500000
    case 2500000: return B2500000;
#endif
#ifdef B3000000
    case 3000000: return B3000000;
#endif
#ifdef B3500000
    case 3500000: return B3500000;
#endif
#ifdef B4000000
    case 4000000: return B4000000;
#endif
    default: return static_cast<speed_t>(0);
  }
}

IoResult map_result(ssize_t result) noexcept {
  if (result > 0) {
    return {TransportStatus::Ok, static_cast<std::size_t>(result), 0};
  }
  if (result == 0) {
    return {TransportStatus::Closed, 0, 0};
  }
  if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) {
    return {TransportStatus::WouldBlock, 0, errno};
  }
  return {TransportStatus::Error, 0, errno};
}

}  // namespace

PosixSerialTransport::PosixSerialTransport(const char* device, int baud_rate) noexcept
    : PosixSerialTransport(PosixSerialOptions{device, baud_rate}) {}

PosixSerialTransport::PosixSerialTransport(
    const PosixSerialOptions& options) noexcept
    : baud_rate_(options.baud_rate), linux_rs485_(options.linux_rs485),
      rts_high_while_sending_(options.rts_high_while_sending),
      delay_before_send_ms_(options.delay_before_send_ms),
      delay_after_send_ms_(options.delay_after_send_ms) {
  if (options.device == nullptr) {
    return;
  }
  const auto length = std::strlen(options.device);
  if (length == 0 || length >= device_.size() || to_speed(baud_rate_) == 0) {
    return;
  }
  std::memcpy(device_.data(), options.device, length + 1);
  config_valid_ = true;
}

PosixSerialTransport::~PosixSerialTransport() { close(); }

TransportStatus PosixSerialTransport::open() noexcept {
  if (!config_valid_ || fd_ >= 0) {
    return TransportStatus::Error;
  }
  fd_ = ::open(device_.data(), O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC);
  if (fd_ < 0) {
    return TransportStatus::Error;
  }
  termios tty{};
  const auto speed = to_speed(baud_rate_);
  if (::tcgetattr(fd_, &tty) != 0) {
    close();
    return TransportStatus::Error;
  }
  ::cfmakeraw(&tty);
  tty.c_cflag |= CLOCAL | CREAD;
  tty.c_cflag &= ~CRTSCTS;
  tty.c_cflag &= ~CSTOPB;
  tty.c_cflag &= ~PARENB;
  tty.c_cflag = (tty.c_cflag & ~CSIZE) | CS8;
  tty.c_cc[VMIN] = 0;
  tty.c_cc[VTIME] = 0;
  if (::cfsetispeed(&tty, speed) != 0 || ::cfsetospeed(&tty, speed) != 0 ||
      ::tcsetattr(fd_, TCSANOW, &tty) != 0) {
    close();
    return TransportStatus::Error;
  }
  if (linux_rs485_) {
    serial_rs485 rs485{};
    rs485.flags = SER_RS485_ENABLED;
    rs485.flags |= rts_high_while_sending_ ? SER_RS485_RTS_ON_SEND
                                           : SER_RS485_RTS_AFTER_SEND;
    rs485.delay_rts_before_send = delay_before_send_ms_;
    rs485.delay_rts_after_send = delay_after_send_ms_;
    if (::ioctl(fd_, TIOCSRS485, &rs485) != 0) {
      close();
      return TransportStatus::Error;
    }
  }
  (void)::tcflush(fd_, TCIOFLUSH);
  return TransportStatus::Ok;
}

IoResult PosixSerialTransport::try_receive(std::byte* destination,
                                           std::size_t capacity) noexcept {
  if (fd_ < 0) {
    return {TransportStatus::Closed, 0, 0};
  }
  if (destination == nullptr || capacity == 0) {
    return {TransportStatus::Error, 0, EINVAL};
  }
  return map_result(::read(fd_, destination, capacity));
}

IoResult PosixSerialTransport::try_send(const std::byte* source,
                                        std::size_t size) noexcept {
  if (fd_ < 0) {
    return {TransportStatus::Closed, 0, 0};
  }
  if (source == nullptr || size == 0) {
    return {TransportStatus::Error, 0, EINVAL};
  }
  return map_result(::write(fd_, source, size));
}

void PosixSerialTransport::close() noexcept {
  if (fd_ >= 0) {
    (void)::close(fd_);
    fd_ = -1;
  }
}

}  // namespace rtctrl::transport
