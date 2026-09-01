#include "rtctrl/protocol/fixed_target_codec.hpp"

#include <cmath>
#include <cstring>
#include <limits>

namespace rtctrl::protocol {
namespace {

constexpr std::size_t kMagicOffset = 0;
constexpr std::size_t kVersionOffset = 4;
constexpr std::size_t kTypeOffset = 5;
constexpr std::size_t kFlagsOffset = 6;
constexpr std::size_t kSessionOffset = 8;
constexpr std::size_t kPayloadSizeOffset = 12;
constexpr std::size_t kJointCountOffset = 14;
constexpr std::size_t kSequenceOffset = 16;
constexpr std::size_t kSenderTimeOffset = 24;
constexpr std::size_t kLeaseOffset = 32;
constexpr std::size_t kPayloadOffset = FixedTargetCodec::kHeaderSize;
constexpr std::size_t kCrcOffset = FixedTargetCodec::kHeaderSize + FixedTargetCodec::kPayloadSize;

void put_u16(std::byte* output, std::uint16_t value) noexcept {
  output[0] = static_cast<std::byte>(value & 0xffU);
  output[1] = static_cast<std::byte>((value >> 8U) & 0xffU);
}

void put_u32(std::byte* output, std::uint32_t value) noexcept {
  for (std::size_t i = 0; i < 4; ++i) {
    output[i] = static_cast<std::byte>((value >> (i * 8U)) & 0xffU);
  }
}

void put_u64(std::byte* output, std::uint64_t value) noexcept {
  for (std::size_t i = 0; i < 8; ++i) {
    output[i] = static_cast<std::byte>((value >> (i * 8U)) & 0xffU);
  }
}

std::uint16_t get_u16(const std::byte* input) noexcept {
  return static_cast<std::uint16_t>(std::to_integer<std::uint8_t>(input[0])) |
         static_cast<std::uint16_t>(std::to_integer<std::uint8_t>(input[1]) << 8U);
}

std::uint32_t get_u32(const std::byte* input) noexcept {
  std::uint32_t value = 0;
  for (std::size_t i = 0; i < 4; ++i) {
    value |= static_cast<std::uint32_t>(std::to_integer<std::uint8_t>(input[i]))
             << (i * 8U);
  }
  return value;
}

std::uint64_t get_u64(const std::byte* input) noexcept {
  std::uint64_t value = 0;
  for (std::size_t i = 0; i < 8; ++i) {
    value |= static_cast<std::uint64_t>(std::to_integer<std::uint8_t>(input[i]))
             << (i * 8U);
  }
  return value;
}

void put_float(std::byte* output, float value) noexcept {
  std::uint32_t bits = 0;
  std::memcpy(&bits, &value, sizeof(bits));
  put_u32(output, bits);
}

float get_float(const std::byte* input) noexcept {
  const auto bits = get_u32(input);
  float value = 0.0F;
  std::memcpy(&value, &bits, sizeof(value));
  return value;
}

}  // namespace

std::uint32_t crc32c(const std::byte* data, std::size_t size) noexcept {
  std::uint32_t crc = 0xffffffffU;
  for (std::size_t i = 0; i < size; ++i) {
    crc ^= std::to_integer<std::uint8_t>(data[i]);
    for (int bit = 0; bit < 8; ++bit) {
      const std::uint32_t mask = 0U - (crc & 1U);
      crc = (crc >> 1U) ^ (0x82f63b78U & mask);
    }
  }
  return ~crc;
}

EncodeResult FixedTargetCodec::encode(const TargetEnvelope& input, std::byte* output,
                                      std::size_t capacity) noexcept {
  static_assert(std::numeric_limits<float>::is_iec559,
                "wire protocol requires IEEE-754 floats");
  if (output == nullptr || capacity < kFrameSize) {
    return {CodecStatus::BufferTooSmall, 0};
  }
  if (input.session_id == 0 || input.sequence == 0 || input.lease_us == 0) {
    return {CodecStatus::InvalidFrame, 0};
  }
  for (double position : input.position) {
    if (!std::isfinite(position)) {
      return {CodecStatus::InvalidFrame, 0};
    }
  }

  std::memset(output, 0, kFrameSize);
  put_u32(output + kMagicOffset, kMagic);
  output[kVersionOffset] = static_cast<std::byte>(kVersion);
  output[kTypeOffset] = static_cast<std::byte>(kTargetFrameType);
  put_u16(output + kFlagsOffset, 0);
  put_u32(output + kSessionOffset, input.session_id);
  put_u16(output + kPayloadSizeOffset, static_cast<std::uint16_t>(kPayloadSize));
  put_u16(output + kJointCountOffset,
          static_cast<std::uint16_t>(model::kJointCount));
  put_u64(output + kSequenceOffset, input.sequence);
  put_u64(output + kSenderTimeOffset, input.sender_time_ns);
  put_u32(output + kLeaseOffset, input.lease_us);
  for (std::size_t i = 0; i < model::kJointCount; ++i) {
    put_float(output + kPayloadOffset + i * sizeof(float),
              static_cast<float>(input.position[i]));
  }
  put_u32(output + kCrcOffset, crc32c(output, kCrcOffset));
  return {CodecStatus::Ok, kFrameSize};
}

DecodeResult FixedTargetCodec::decode(const std::byte* input, std::size_t size,
                                      TargetEnvelope& output) noexcept {
  if (input == nullptr || size == 0) {
    return {CodecStatus::NeedMoreData, 0};
  }
  if (size < sizeof(std::uint32_t)) {
    return {CodecStatus::NeedMoreData, 0};
  }
  if (get_u32(input + kMagicOffset) != kMagic) {
    return {CodecStatus::InvalidFrame, 1};
  }
  if (size < kHeaderSize) {
    return {CodecStatus::NeedMoreData, 0};
  }
  if (std::to_integer<std::uint8_t>(input[kVersionOffset]) != kVersion) {
    return {CodecStatus::UnsupportedVersion, 1};
  }
  const bool shape_valid =
      std::to_integer<std::uint8_t>(input[kTypeOffset]) == kTargetFrameType &&
      get_u16(input + kFlagsOffset) == 0 &&
      get_u16(input + kPayloadSizeOffset) == kPayloadSize &&
      get_u16(input + kJointCountOffset) == model::kJointCount;
  if (!shape_valid) {
    return {CodecStatus::InvalidFrame, 1};
  }
  if (size < kFrameSize) {
    return {CodecStatus::NeedMoreData, 0};
  }
  if (get_u32(input + kCrcOffset) != crc32c(input, kCrcOffset)) {
    return {CodecStatus::InvalidFrame, kFrameSize};
  }

  TargetEnvelope decoded{};
  decoded.session_id = get_u32(input + kSessionOffset);
  decoded.sequence = get_u64(input + kSequenceOffset);
  decoded.sender_time_ns = get_u64(input + kSenderTimeOffset);
  decoded.lease_us = get_u32(input + kLeaseOffset);
  if (decoded.session_id == 0 || decoded.sequence == 0 || decoded.lease_us == 0) {
    return {CodecStatus::InvalidFrame, kFrameSize};
  }
  for (std::size_t i = 0; i < model::kJointCount; ++i) {
    decoded.position[i] = static_cast<double>(
        get_float(input + kPayloadOffset + i * sizeof(float)));
    if (!std::isfinite(decoded.position[i])) {
      return {CodecStatus::InvalidFrame, kFrameSize};
    }
  }
  output = decoded;
  return {CodecStatus::Ok, kFrameSize};
}

}  // namespace rtctrl::protocol
