#include "rtctrl/ipc/posix_shared_memory.hpp"

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <new>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace rtctrl::ipc {

PosixSharedMemoryRegion::~PosixSharedMemoryRegion() { close(); }

bool PosixSharedMemoryRegion::set_name(const char* name) noexcept {
  if (name == nullptr) {
    last_error_ = EINVAL;
    return false;
  }
  const auto length = std::strlen(name);
  if (length == 0 || length + 2 > name_.size()) {
    last_error_ = ENAMETOOLONG;
    return false;
  }
  name_.fill('\0');
  if (name[0] == '/') {
    std::memcpy(name_.data(), name, length + 1);
  } else {
    name_[0] = '/';
    std::memcpy(name_.data() + 1, name, length + 1);
  }
  return true;
}

bool PosixSharedMemoryRegion::map_existing(bool owner) noexcept {
  void* address = ::mmap(nullptr, sizeof(SharedMotorRegion), PROT_READ | PROT_WRITE,
                         MAP_SHARED, fd_, 0);
  if (address == MAP_FAILED) {
    last_error_ = errno;
    return false;
  }
  region_ = static_cast<SharedMotorRegion*>(address);
  owner_ = owner;
  return true;
}

bool PosixSharedMemoryRegion::create_owner(const char* name) noexcept {
  close();
  if (!set_name(name)) {
    return false;
  }
  fd_ = ::shm_open(name_.data(), O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0660);
  if (fd_ < 0) {
    last_error_ = errno;
    return false;
  }
  if (::ftruncate(fd_, static_cast<off_t>(sizeof(SharedMotorRegion))) != 0 ||
      !map_existing(true)) {
    const int error = last_error_ == 0 ? errno : last_error_;
    close();
    last_error_ = error;
    return false;
  }
  initialize_shared_motor_region(*region_);
  last_error_ = 0;
  return true;
}

bool PosixSharedMemoryRegion::attach(const char* name) noexcept {
  close();
  if (!set_name(name)) {
    return false;
  }
  fd_ = ::shm_open(name_.data(), O_RDWR | O_CLOEXEC, 0);
  if (fd_ < 0) {
    last_error_ = errno;
    return false;
  }
  struct stat status {};
  int validation_error = 0;
  if (::fstat(fd_, &status) != 0) {
    validation_error = errno;
  } else if (status.st_size != static_cast<off_t>(sizeof(SharedMotorRegion))) {
    validation_error = EPROTO;
  } else if (!map_existing(false)) {
    validation_error = last_error_;
  } else if (!valid_shared_motor_region(*region_)) {
    validation_error = EPROTO;
  }
  if (validation_error != 0) {
    close();
    last_error_ = validation_error;
    return false;
  }
  last_error_ = 0;
  return true;
}

void PosixSharedMemoryRegion::close() noexcept {
  if (region_ != nullptr) {
    (void)::munmap(region_, sizeof(SharedMotorRegion));
    region_ = nullptr;
  }
  if (fd_ >= 0) {
    (void)::close(fd_);
    fd_ = -1;
  }
  if (owner_ && name_[0] != '\0') {
    (void)::shm_unlink(name_.data());
  }
  owner_ = false;
  name_.fill('\0');
}

}  // namespace rtctrl::ipc
