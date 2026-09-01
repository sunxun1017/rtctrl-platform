#pragma once

#include "rtctrl/hal/actuator_hal.hpp"
#include "rtctrl/ipc/kernel_mailbox_codec.hpp"

#include <cstdint>

namespace rtctrl::hal {

struct KernelMailboxHalConfig {
  // Select the exact /dev/rtctrl-mailbox-<platform-device> node, or a stable
  // udev symlink. There is deliberately no implicit hardware default.
  const char* device_path{nullptr};
  std::int64_t max_feedback_age_ns{20'000'000};
};

// Linux userspace adapter for the versioned kernel-staged DMA mailbox. The
// fixed-size ioctls are bounded and allocation-free; userspace never maps or
// mutates device-owned DMA slots.
class KernelMailboxHal final : public IActuatorHal {
public:
  explicit KernelMailboxHal(KernelMailboxHalConfig config) noexcept
      : config_(config) {}
  ~KernelMailboxHal() override;

  KernelMailboxHal(const KernelMailboxHal&) = delete;
  KernelMailboxHal& operator=(const KernelMailboxHal&) = delete;

  HalStatus open_safe(std::int64_t now_ns) noexcept override;
  HalStatus arm(std::int64_t now_ns) noexcept override;
  HalStatus read(std::int64_t now_ns, model::SensorFrame& output) noexcept override;
  HalStatus write(std::int64_t now_ns,
                  const model::CommandFrame& input) noexcept override;
  void emergency_stop(std::int64_t now_ns) noexcept override;
  void close() noexcept override;

  int last_errno() const noexcept { return last_errno_; }

private:
  void remember_errno() noexcept;

  KernelMailboxHalConfig config_{};
  int fd_{-1};
  std::int64_t watchdog_timeout_ns_{0};
  std::uint64_t submit_sequence_{0};
  model::SensorFrame last_feedback_{};
  int last_errno_{0};
  bool opened_{false};
  bool armed_{false};
  bool have_feedback_{false};
};

}  // namespace rtctrl::hal
