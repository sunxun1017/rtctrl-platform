#include "rtctrl/transport/loopback_source.hpp"

#include <cmath>

namespace rtctrl::transport {

bool LoopbackSource::poll(std::int64_t now_ns, model::ControlTarget& target) noexcept {
  constexpr double kTau = 6.28318530717958647692;
  if (start_ns_ == 0) {
    start_ns_ = now_ns;
  }
  const double elapsed = static_cast<double>(now_ns - start_ns_) / 1.0e9;
  target = {};
  target.sequence = ++sequence_;
  target.created_time_ns = now_ns;
  target.valid_until_ns = now_ns + 100'000'000LL;
  for (std::size_t i = 0; i < model::kJointCount; ++i) {
    const double phase = static_cast<double>(i) * 0.25;
    target.position[i] = amplitude_rad_ * std::sin(kTau * frequency_hz_ * elapsed + phase);
  }
  return true;
}

}  // namespace rtctrl::transport
