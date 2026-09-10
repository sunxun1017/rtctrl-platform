#include "rtctrl/bridge/target_arbiter.hpp"
#include <algorithm>
#include <cmath>
#include <limits>

namespace rtctrl::bridge {

bool TargetArbiter::bind(std::size_t slot,
                         ICommandSource& source,
                         unsigned priority) noexcept {
    if (started_ || slot >= sources_.size() || sources_[slot].input ||
        lease_ns_ <= 0) {
        return false;
    }
    for (const auto& entry : sources_) {
        if (entry.input == &source) {
            return false;
        }
    }
    sources_[slot].input = &source;
    sources_[slot].priority = priority;
    return true;
}

bool TargetArbiter::poll(std::int64_t now_ns) noexcept {
    started_ = true;
    if (now_ns < 0 || lease_ns_ <= 0) {
        return false;
    }
    std::size_t winner = kMaxSources;
    for (std::size_t i = 0; i < sources_.size(); ++i) {
        auto& entry = sources_[i];
        if (!entry.input) {
            continue;
        }
        model::ControlTarget target{};
        if (entry.input->poll(now_ns, target)) {
            const bool finite =
                std::all_of(target.position.begin(),
                            target.position.end(),
                            [](double value) { return std::isfinite(value); });
            if (!finite || target.sequence <= entry.sequence ||
                target.created_time_ns < 0 || target.created_time_ns > now_ns ||
                now_ns - target.created_time_ns >= lease_ns_ ||
                target.created_time_ns >
                    std::numeric_limits<std::int64_t>::max() - lease_ns_ ||
                (target.valid_until_ns != 0 && target.valid_until_ns <= now_ns)) {
                ++rejected_;
            } else {
                const auto local_deadline = target.created_time_ns + lease_ns_;
                target.valid_until_ns =
                    target.valid_until_ns == 0
                        ? local_deadline
                        : std::min(target.valid_until_ns, local_deadline);
                entry.latest = target;
                entry.sequence = target.sequence;
                entry.valid = true;
            }
        }
        if (entry.valid && entry.latest.valid_until_ns > now_ns &&
            (winner == kMaxSources || entry.priority > sources_[winner].priority)) {
            winner = i;
        }
    }
    if (winner == kMaxSources ||
        (published_slot_ == winner &&
         published_sequence_ == sources_[winner].sequence) ||
        output_sequence_ == std::numeric_limits<std::uint64_t>::max()) {
        return false;
    }
    auto target = sources_[winner].latest;
    target.sequence = output_sequence_ + 1;
    if (!ingress_.try_submit(target)) {
        ++backpressure_;
        return false;
    }
    output_sequence_ = target.sequence;
    published_slot_ = winner;
    published_sequence_ = sources_[winner].sequence;
    return true;
}

} // namespace rtctrl::bridge
