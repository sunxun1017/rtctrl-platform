#pragma once
#include <cstdint>
#include <type_traits>

namespace rtctrl::vision {
// In-process semantic contract, NOT a wire or shared-memory ABI. An external
// adapter must decode/version-check and map remote time to local monotonic time.
enum class SceneState : std::uint8_t { Unknown, Clear, Active, Fault };
struct Observation {
    std::uint32_t schema_version{1};
    std::uint64_t session{0};
    std::uint64_t sequence{0};
    std::int64_t capture_time_ns{0};
    std::int64_t valid_until_ns{0};
    SceneState scene{SceneState::Unknown};
};
static_assert(std::is_trivially_copyable_v<Observation>);
} // namespace rtctrl::vision
