#include "rtctrl/transport/framed_command_source.hpp"

#include <algorithm>
#include <cstring>
#include <limits>

namespace rtctrl::transport {

TransportStatus FramedCommandSource::open() noexcept {
    reset_link_session();
    const auto status = transport_.open();
    open_ = status == TransportStatus::Ok;
    return status;
}

void FramedCommandSource::close() noexcept {
    transport_.close();
    open_ = false;
    reset_link_session();
}

void FramedCommandSource::reset_link_session() noexcept {
    codec_.reset();
    rx_size_ = 0;
    session_id_ = 0;
    last_sequence_ = 0;
    last_sender_time_ns_ = 0;
}

void FramedCommandSource::consume(std::size_t count) noexcept {
    count = std::min(count, rx_size_);
    std::memmove(rx_.data(), rx_.data() + count, rx_size_ - count);
    rx_size_ -= count;
}

bool FramedCommandSource::poll(std::int64_t now_ns, model::ControlTarget& target) noexcept {
    if (!open_ || now_ns < 0 || policy_.max_lease_us == 0 || policy_.max_frames_per_poll == 0) {
        return false;
    }
    if (rx_size_ == kRxCapacity) {
        consume(1);
        ++metrics_.bytes_discarded;
    }
    const auto io = transport_.try_receive(rx_.data() + rx_size_, kRxCapacity - rx_size_);
    if (io.status == TransportStatus::Ok) {
        if (io.bytes <= kRxCapacity - rx_size_) {
            rx_size_ += io.bytes;
        } else {
            ++metrics_.transport_errors;
            rx_size_ = 0;
        }
    } else if (io.status != TransportStatus::WouldBlock && io.status != TransportStatus::Timeout) {
        ++metrics_.transport_errors;
    }

    bool have_target = false;
    model::ControlTarget latest{};
    std::size_t frames_seen = 0;
    std::size_t parse_steps = 0;
    while (rx_size_ > 0 && frames_seen < policy_.max_frames_per_poll && parse_steps < kRxCapacity) {
        ++parse_steps;
        protocol::TargetEnvelope envelope{};
        const auto decoded = codec_.decode(rx_.data(), rx_size_, envelope);
        if (decoded.status == protocol::CodecStatus::NeedMoreData) {
            break;
        }
        if (decoded.status != protocol::CodecStatus::Ok) {
            const auto discarded = decoded.consumed == 0 ? 1 : decoded.consumed;
            metrics_.bytes_discarded += discarded;
            ++metrics_.framing_errors;
            consume(discarded);
            continue;
        }
        consume(decoded.consumed);
        ++frames_seen;

        if (session_id_ == 0) {
            session_id_ = envelope.session_id;
        } else if (envelope.session_id != session_id_) {
            ++metrics_.session_errors;
            continue;
        }
        if (envelope.sequence <= last_sequence_) {
            ++metrics_.replayed_frames;
            continue;
        }
        if (last_sender_time_ns_ != 0 && envelope.sender_time_ns < last_sender_time_ns_) {
            ++metrics_.sender_time_regressions;
            continue;
        }

        const auto lease_us = std::min(envelope.lease_us, policy_.max_lease_us);
        if (lease_us == 0 || now_ns > std::numeric_limits<std::int64_t>::max() -
                                          static_cast<std::int64_t>(lease_us) * 1000LL) {
            ++metrics_.expired_frames;
            continue;
        }
        latest = {};
        latest.sequence = envelope.sequence;
        // Convert the relative wire lease into the receiver's monotonic clock domain.
        latest.created_time_ns = now_ns;
        latest.valid_until_ns = now_ns + static_cast<std::int64_t>(lease_us) * 1000LL;
        latest.position = envelope.position;
        last_sequence_ = envelope.sequence;
        last_sender_time_ns_ = envelope.sender_time_ns;
        ++metrics_.frames_ok;
        have_target = true;
    }
    if (have_target) {
        target = latest;
    }
    return have_target;
}

} // namespace rtctrl::transport
