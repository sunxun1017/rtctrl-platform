#pragma once

#include "rtctrl/protocol/target_codec.hpp"

#include <cstddef>
#include <cstdint>

namespace rtctrl::protocol {

// Wire format is explicitly little-endian and never serializes a C++ struct.
// This keeps AArch64/RISC-V/x86 interoperable despite padding and alignment.
class FixedTargetCodec final : public ITargetCodec {
  public:
    static constexpr std::uint32_t kMagic = 0x4c435452U; // "RTCL" on wire.
    static constexpr std::uint8_t kVersion = 2;
    static constexpr std::uint8_t kTargetFrameType = 1;
    static constexpr std::size_t kHeaderSize = 36;
    static constexpr std::size_t kPayloadSize = model::kJointCount * sizeof(float);
    static constexpr std::size_t kFrameSize = kHeaderSize + kPayloadSize + sizeof(std::uint32_t);

    EncodeResult encode(const TargetEnvelope& input, std::byte* output,
                        std::size_t capacity) noexcept override;
    DecodeResult decode(const std::byte* input, std::size_t size,
                        TargetEnvelope& output) noexcept override;
    void reset() noexcept override {}
};

std::uint32_t crc32c(const std::byte* data, std::size_t size) noexcept;

} // namespace rtctrl::protocol
