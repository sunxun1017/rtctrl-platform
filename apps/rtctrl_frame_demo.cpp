#include "rtctrl/protocol/fixed_target_codec.hpp"
#include "rtctrl/transport/framed_command_source.hpp"
#include "rtctrl/transport/loopback_byte_transport.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <iostream>

int main() {
  rtctrl::protocol::FixedTargetCodec codec;
  rtctrl::transport::LoopbackByteTransport link(7);
  rtctrl::transport::FramedCommandSource source(link, codec);
  if (source.open() != rtctrl::transport::TransportStatus::Ok) {
    std::cerr << "failed to open loopback link\n";
    return 1;
  }

  rtctrl::protocol::TargetEnvelope envelope{};
  envelope.session_id = 0x53580001U;
  envelope.sequence = 42;
  envelope.sender_time_ns = 9'000'000;
  envelope.lease_us = 50'000;
  for (std::size_t i = 0; i < envelope.position.size(); ++i) {
    envelope.position[i] = 0.1 * static_cast<double>(i + 1);
  }

  std::array<std::byte, rtctrl::protocol::FixedTargetCodec::kFrameSize> wire{};
  const auto encoded = codec.encode(envelope, wire.data(), wire.size());
  if (encoded.status != rtctrl::protocol::CodecStatus::Ok ||
      !link.inject(wire.data(), encoded.produced)) {
    std::cerr << "failed to encode/inject target frame\n";
    return 2;
  }

  rtctrl::model::ControlTarget target{};
  bool received = false;
  std::int64_t receiver_now_ns = 1'000'000'000;
  for (int attempt = 0; attempt < 16 && !received; ++attempt) {
    received = source.poll(receiver_now_ns, target);
    receiver_now_ns += 1'000'000;
  }
  if (!received) {
    std::cerr << "fragmented frame was not reconstructed\n";
    return 3;
  }

  const auto& metrics = source.metrics();
  std::cout << "{\n"
            << "  \"wire_bytes\": " << encoded.produced << ",\n"
            << "  \"sequence\": " << target.sequence << ",\n"
            << "  \"local_lease_us\": "
            << (target.valid_until_ns - target.created_time_ns) / 1000 << ",\n"
            << "  \"frames_ok\": " << metrics.frames_ok << ",\n"
            << "  \"framing_errors\": " << metrics.framing_errors << ",\n"
            << "  \"positions\": [";
  for (std::size_t i = 0; i < target.position.size(); ++i) {
    if (i != 0) {
      std::cout << ", ";
    }
    std::cout << std::fixed << std::setprecision(3) << target.position[i];
  }
  std::cout << "]\n}\n";
  source.close();
  return 0;
}
