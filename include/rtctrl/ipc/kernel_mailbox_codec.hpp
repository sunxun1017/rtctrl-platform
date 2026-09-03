#pragma once

#include "rtctrl/model/frames.hpp"

#include <linux/rtctrl_mailbox.h>

#include <cstdint>

namespace rtctrl::ipc {

enum class MailboxFrameStatus : std::uint8_t {
    Ok = 0,
    InvalidFrame,
    Stale,
};

MailboxFrameStatus encode_mailbox_command(const model::CommandFrame& input,
                                          rtctrl_mb_command_frame& output) noexcept;

MailboxFrameStatus decode_mailbox_feedback(const rtctrl_mb_feedback_frame& input,
                                           std::int64_t now_ns, std::int64_t max_age_ns,
                                           model::SensorFrame& output) noexcept;

} // namespace rtctrl::ipc
