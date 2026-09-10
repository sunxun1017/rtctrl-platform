#include <linux/rtctrl_mailbox.h>

#include <stddef.h>
#include <stdint.h>

_Static_assert((RTCTRL_MB_RING_DEPTH & (RTCTRL_MB_RING_DEPTH - 1U)) == 0U,
               "ring depth must be a power of two");
_Static_assert(RTCTRL_MB_UAPI_ABI_VERSION == 2U, "test targets staged-I/O UAPI V2");
_Static_assert(RTCTRL_MB_HW_ABI_VERSION == 2U,
               "endpoint DMA/register ABI requires quiesce handshake V2");
_Static_assert(RTCTRL_MB_MAX_JOINTS == 64U, "ABI has 64 fixed slots");
_Static_assert(sizeof(struct rtctrl_mb_layout) <= UINT32_MAX,
               "layout_bytes remains representable in UAPI");
_Static_assert(offsetof(struct rtctrl_mb_layout, command) % 8U == 0U,
               "command ring keeps 64-bit frame fields aligned");
_Static_assert(offsetof(struct rtctrl_mb_layout, feedback) % 8U == 0U,
               "feedback ring keeps 64-bit frame fields aligned");
_Static_assert(_IOC_SIZE(RTCTRL_MB_IOC_GET_INFO) == sizeof(struct rtctrl_mb_info),
               "GET_INFO ioctl encodes the ABI size");
_Static_assert(_IOC_SIZE(RTCTRL_MB_IOC_SUBMIT_COMMAND) == sizeof(struct rtctrl_mb_command_frame),
               "SUBMIT_COMMAND ioctl encodes the ABI size");
_Static_assert(_IOC_SIZE(RTCTRL_MB_IOC_READ_FEEDBACK) == sizeof(struct rtctrl_mb_feedback_frame),
               "READ_FEEDBACK ioctl encodes the ABI size");

int main(void) {
    return 0;
}
