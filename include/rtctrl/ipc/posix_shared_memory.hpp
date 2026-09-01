#pragma once

#include "rtctrl/ipc/shared_motor_abi.hpp"

#include <array>
#include <cstddef>

namespace rtctrl::ipc {

class PosixSharedMemoryRegion {
public:
  static constexpr std::size_t kNameCapacity = 96;

  PosixSharedMemoryRegion() noexcept = default;
  ~PosixSharedMemoryRegion();
  PosixSharedMemoryRegion(const PosixSharedMemoryRegion&) = delete;
  PosixSharedMemoryRegion& operator=(const PosixSharedMemoryRegion&) = delete;

  // create_owner uses O_EXCL and never replaces an existing segment.
  bool create_owner(const char* name) noexcept;
  bool attach(const char* name) noexcept;
  void close() noexcept;
  SharedMotorRegion* get() noexcept { return region_; }
  const SharedMotorRegion* get() const noexcept { return region_; }
  int last_error() const noexcept { return last_error_; }

private:
  bool set_name(const char* name) noexcept;
  bool map_existing(bool owner) noexcept;

  std::array<char, kNameCapacity> name_{};
  int fd_{-1};
  int last_error_{0};
  SharedMotorRegion* region_{nullptr};
  bool owner_{false};
};

}  // namespace rtctrl::ipc
