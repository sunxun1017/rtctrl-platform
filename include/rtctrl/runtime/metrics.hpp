#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>

namespace rtctrl::runtime {

struct LoopMetrics {
    static constexpr std::int64_t kBucketWidthNs = 10'000;
    static constexpr std::size_t kBucketCount = 512;

    std::uint64_t samples{0};
    std::uint64_t skipped_periods{0};
    std::uint64_t histogram_overflows{0};
    std::uint64_t queue_drops{0};
    std::uint64_t stale_commands{0};
    std::uint64_t io_errors{0};
    std::int64_t max_jitter_ns{0};
    std::int64_t max_execution_ns{0};
    std::array<std::uint64_t, kBucketCount> jitter_histogram{};

    void record_wakeup(std::int64_t jitter_ns, std::uint64_t skipped) noexcept {
        const auto magnitude = jitter_ns >= 0 ? jitter_ns : -jitter_ns;
        max_jitter_ns = std::max(max_jitter_ns, magnitude);
        const auto raw = static_cast<std::uint64_t>(magnitude / kBucketWidthNs);
        if (raw >= kBucketCount) {
            ++histogram_overflows;
        }
        const auto bucket = static_cast<std::size_t>(
            std::min<std::uint64_t>(raw, static_cast<std::uint64_t>(kBucketCount - 1)));
        ++jitter_histogram[bucket];
        ++samples;
        skipped_periods += skipped;
    }

    void record_execution(std::int64_t execution_ns) noexcept {
        max_execution_ns = std::max(max_execution_ns, execution_ns);
    }

    std::int64_t percentile_ns(double quantile) const noexcept {
        if (samples == 0) {
            return 0;
        }
        const auto wanted =
            static_cast<std::uint64_t>(std::ceil(quantile * static_cast<double>(samples)));
        const auto threshold = std::max<std::uint64_t>(1, wanted);
        std::uint64_t cumulative = 0;
        for (std::size_t i = 0; i < kBucketCount; ++i) {
            cumulative += jitter_histogram[i];
            if (cumulative >= threshold) {
                return static_cast<std::int64_t>(i + 1) * kBucketWidthNs;
            }
        }
        return static_cast<std::int64_t>(kBucketCount) * kBucketWidthNs;
    }
};

} // namespace rtctrl::runtime
