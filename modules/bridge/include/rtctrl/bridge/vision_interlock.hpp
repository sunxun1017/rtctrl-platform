#pragma once
#include "rtctrl/runtime/runtime_ports.hpp"
#include "rtctrl/vision/observation.hpp"

namespace rtctrl::bridge {
// Optional product policy: require a fresh Clear observation. Single management
// owner calls update/check. Active, unknown, fault, invalid data or silence
// requests terminal disarm. This cannot authorize motion or reset a fault.
class VisionInterlock {
  public:
    explicit VisionInterlock(runtime::ILifecycleControl& lifecycle,
                             std::uint64_t session,
                             std::int64_t max_age_ns = 100'000'000) noexcept
        : lifecycle_(lifecycle)
        , session_(session)
        , max_age_ns_(max_age_ns) {}
    bool update(const vision::Observation& observation,
                std::int64_t now_ns) noexcept {
        if (tripped_) {
            return false;
        }
        if (max_age_ns_ <= 0 || now_ns < 0 || observation.schema_version != 1 ||
            observation.session != session_ || observation.sequence <= sequence_ ||
            observation.capture_time_ns < 0 ||
            observation.capture_time_ns > now_ns ||
            now_ns - observation.capture_time_ns >= max_age_ns_ ||
            observation.valid_until_ns <= now_ns ||
            observation.scene != vision::SceneState::Clear) {
            trip();
            return false;
        }
        latest_ = observation;
        sequence_ = observation.sequence;
        has_observation_ = true;
        return true;
    }
    bool check(std::int64_t now_ns) noexcept {
        if (tripped_) {
            return false;
        }
        if (!has_observation_ || now_ns < latest_.capture_time_ns ||
            now_ns >= latest_.valid_until_ns ||
            now_ns - latest_.capture_time_ns >= max_age_ns_) {
            trip();
            return false;
        }
        return true;
    }

  private:
    void trip() noexcept {
        tripped_ = true;
        lifecycle_.request_disarm();
    }
    runtime::ILifecycleControl& lifecycle_;
    std::uint64_t session_;
    std::int64_t max_age_ns_;
    std::uint64_t sequence_{0};
    vision::Observation latest_{};
    bool has_observation_{false};
    bool tripped_{false};
};
} // namespace rtctrl::bridge
