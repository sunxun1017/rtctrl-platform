#pragma once

#include "rtctrl/model/frames.hpp"

#include <array>
#include <cstddef>
#include <cstdint>

namespace rtctrl::protocol {

enum class CodecStatus : std::uint8_t {
  Ok,
  NeedMoreData,
  BufferTooSmall,
  InvalidFrame,
  UnsupportedVersion
};

struct EncodeResult {
  CodecStatus status{CodecStatus::InvalidFrame};
  std::size_t produced{0};
};

struct DecodeResult {
  CodecStatus status{CodecStatus::InvalidFrame};
  std::size_t consumed{0};
};

struct TargetEnvelope {
  std::uint32_t session_id{0};
  std::uint64_t sequence{0};
  std::uint64_t sender_time_ns{0};
  std::uint32_t lease_us{0};
  std::array<double, model::kJointCount> position{};
};

class ITargetCodec {
public:
  virtual ~ITargetCodec() = default;

  // Pure, bounded protocol processing: no system calls and no dynamic allocation.
  virtual EncodeResult encode(const TargetEnvelope& input, std::byte* output,
                              std::size_t capacity) noexcept = 0;
  virtual DecodeResult decode(const std::byte* input, std::size_t size,
                              TargetEnvelope& output) noexcept = 0;
  virtual void reset() noexcept = 0;
};

}  // namespace rtctrl::protocol
