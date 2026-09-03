#include "rtctrl/hal/kernel_mailbox_hal.hpp"

#include <linux/rtctrl_mailbox.h>

#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <fcntl.h>
#include <limits>
#include <sys/ioctl.h>
#include <unistd.h>

namespace rtctrl::hal {

KernelMailboxHal::~KernelMailboxHal() {
    close();
}

void KernelMailboxHal::remember_errno() noexcept {
    last_errno_ = errno == 0 ? EIO : errno;
}

HalStatus KernelMailboxHal::open_safe(std::int64_t) noexcept {
    if (opened_ || config_.device_path == nullptr || config_.device_path[0] == '\0' ||
        config_.max_feedback_age_ns <= 0) {
        last_errno_ = EINVAL;
        return HalStatus::IoError;
    }
    fd_ = ::open(config_.device_path, O_RDWR | O_CLOEXEC | O_NONBLOCK);
    if (fd_ < 0) {
        remember_errno();
        return HalStatus::IoError;
    }

    rtctrl_mb_info info{};
    if (::ioctl(fd_, RTCTRL_MB_IOC_GET_INFO, &info) != 0) {
        remember_errno();
        close();
        return HalStatus::IoError;
    }
    if (info.abi_version != RTCTRL_MB_UAPI_ABI_VERSION ||
        (info.capabilities & (RTCTRL_MB_CAP_KERNEL_STAGED_IO | RTCTRL_MB_CAP_WATCHDOG)) !=
            (RTCTRL_MB_CAP_KERNEL_STAGED_IO | RTCTRL_MB_CAP_WATCHDOG) ||
        info.max_joints < model::kJointCount || info.joint_count != model::kJointCount ||
        info.ring_depth != RTCTRL_MB_RING_DEPTH) {
        last_errno_ = EPROTO;
        close();
        return HalStatus::IoError;
    }
    watchdog_timeout_ns_ = static_cast<std::int64_t>(info.watchdog_timeout_us) * 1'000;
    if (::ioctl(fd_, RTCTRL_MB_IOC_DISARM) != 0) {
        remember_errno();
        close();
        return HalStatus::IoError;
    }

    opened_ = true;
    armed_ = false;
    have_feedback_ = false;
    submit_sequence_ = 0;
    last_errno_ = 0;
    return HalStatus::Ok;
}

HalStatus KernelMailboxHal::arm(std::int64_t now_ns) noexcept {
    if (!opened_ || !have_feedback_ || last_feedback_.fault_bits != 0U) {
        last_errno_ = EAGAIN;
        return HalStatus::NotReady;
    }
    if (submit_sequence_ == std::numeric_limits<std::uint64_t>::max()) {
        last_errno_ = EOVERFLOW;
        return HalStatus::IoError;
    }
    const auto next_sequence = submit_sequence_ + 1U;
    model::CommandFrame safe{};
    safe.sequence = next_sequence;
    safe.created_time_ns = now_ns;
    safe.valid_until_ns =
        now_ns + watchdog_timeout_ns_ + static_cast<std::int64_t>(RTCTRL_MB_MIN_REMAINING_LEASE_NS);
    safe.mode = model::CommandMode::SafeStop;
    for (std::size_t i = 0; i < model::kJointCount; ++i) {
        safe.target_position[i] = last_feedback_.position[i];
        safe.kd[i] = 2.0;
    }
    rtctrl_mb_command_frame frame{};
    if (ipc::encode_mailbox_command(safe, frame) != ipc::MailboxFrameStatus::Ok) {
        last_errno_ = EPROTO;
        return HalStatus::IoError;
    }
    if (::ioctl(fd_, RTCTRL_MB_IOC_SUBMIT_COMMAND, &frame) != 0) {
        remember_errno();
        return HalStatus::IoError;
    }
    submit_sequence_ = next_sequence;
    if (::ioctl(fd_, RTCTRL_MB_IOC_ARM) != 0) {
        remember_errno();
        return HalStatus::IoError;
    }
    armed_ = true;
    last_errno_ = 0;
    return HalStatus::Ok;
}

HalStatus KernelMailboxHal::read(std::int64_t now_ns, model::SensorFrame& output) noexcept {
    if (!opened_) {
        last_errno_ = ENODEV;
        return HalStatus::NotReady;
    }
    rtctrl_mb_feedback_frame frame{};
    if (::ioctl(fd_, RTCTRL_MB_IOC_READ_FEEDBACK, &frame) != 0) {
        const int error = errno;
        if (error == EAGAIN && have_feedback_ && last_feedback_.sample_time_ns <= now_ns &&
            now_ns - last_feedback_.sample_time_ns <= config_.max_feedback_age_ns) {
            output = last_feedback_;
            return output.fault_bits == 0U ? HalStatus::Ok : HalStatus::IoError;
        }
        last_errno_ = error == 0 ? EIO : error;
        return error == EAGAIN ? HalStatus::NotReady : HalStatus::IoError;
    }
    const auto status =
        ipc::decode_mailbox_feedback(frame, now_ns, config_.max_feedback_age_ns, output);
    if (status != ipc::MailboxFrameStatus::Ok) {
        last_errno_ = status == ipc::MailboxFrameStatus::Stale ? ESTALE : EPROTO;
        return HalStatus::IoError;
    }
    last_feedback_ = output;
    have_feedback_ = true;
    last_errno_ = output.fault_bits == 0U ? 0 : EIO;
    return output.fault_bits == 0U ? HalStatus::Ok : HalStatus::IoError;
}

HalStatus KernelMailboxHal::write(std::int64_t now_ns, const model::CommandFrame& input) noexcept {
    if (!opened_ || !armed_ || input.created_time_ns > now_ns || input.valid_until_ns <= now_ns) {
        last_errno_ = EAGAIN;
        return HalStatus::NotReady;
    }
    rtctrl_mb_command_frame frame{};
    if (ipc::encode_mailbox_command(input, frame) != ipc::MailboxFrameStatus::Ok) {
        last_errno_ = EPROTO;
        return HalStatus::IoError;
    }
    if (submit_sequence_ == std::numeric_limits<std::uint64_t>::max()) {
        last_errno_ = EOVERFLOW;
        return HalStatus::IoError;
    }
    const auto next_sequence = submit_sequence_ + 1U;
    // The UAPI sequence is a transport anti-replay counter, independent of the
    // controller's logical sequence.
    frame.sequence = next_sequence;
    if (::ioctl(fd_, RTCTRL_MB_IOC_SUBMIT_COMMAND, &frame) != 0) {
        remember_errno();
        armed_ = false;
        return HalStatus::IoError;
    }
    submit_sequence_ = next_sequence;
    last_errno_ = 0;
    return HalStatus::Ok;
}

void KernelMailboxHal::emergency_stop(std::int64_t) noexcept {
    if (fd_ >= 0 && ::ioctl(fd_, RTCTRL_MB_IOC_DISARM) != 0) {
        remember_errno();
    }
    armed_ = false;
}

void KernelMailboxHal::close() noexcept {
    if (fd_ >= 0) {
        emergency_stop(0);
    }
    watchdog_timeout_ns_ = 0;
    submit_sequence_ = 0;
    if (fd_ >= 0) {
        (void)::close(fd_);
    }
    fd_ = -1;
    opened_ = false;
    armed_ = false;
    have_feedback_ = false;
}

} // namespace rtctrl::hal
