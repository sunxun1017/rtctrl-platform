# RKAIQ server failure handling and RV1126B hang investigation

## Fixed: initialization and startup failure handling

SDK camera_engine_rkaiq commit `91dee445c13770279e3ee90cd82bd278c5306f85`.
The observed missing-IQ failure returned NULL from sysctl_init. The server immediately passed that NULL to setListenStrmStatus. Board GDB showed common_getSysCtxArray -> setListenStrmStatus -> server. Patch 0001 exits with EXIT_FAILURE before any context API call.

Code inspection also found start_engine called sysctl_start before checking the context, and ignored its return code. Patch 0002 validates the context first and reports nonzero start results as failure instead of printing success. A process-level exit matches this server's existing fail-fast policy; this does not implement graceful recovery of other cameras.

The vendor SDK is not edited. Generate a reviewable copy:

```sh
python3 scripts/prepare-rkaiq-server-fix.py --sdk-root /path/to/sdk --output /path/outside/sdk/server-fixed
python3 scripts/test-rkaiq-server-errors.py --sdk-root /path/to/sdk
```

The regression compiles the actual patched server source and stubs the RKAIQ entry points. It checks missing IQ / NULL initialization, NULL start context, failed start, and successful start in child processes. This is host error-path validation, not a board binary deployment or image-quality test.

## Not yet fixed: long-capture shutdown and system stall

A 9000-frame run produced sequences 0..8999 at about 30.05 FPS. At shutdown it printed STOP_BEGIN then LIFECYCLE_TIMEOUT. Kernel events in order:

- 9724.073518: rockchip_dmcfreq_wait_complete timed out waiting for wait_ctrl.complt_irq.
- 9755.341536: rcu_sched detected a CPU0 stall; task dump named irqbalance.
- Repeated CPU0 stall at 9935.361632. Normal reboot failed to restore the board; a physical reset was required.

RV1126B's compatible selects rk3568_dmc_init in drivers/devfreq/rockchip_dmc.c. That path starts DDR MCU frequency transitions and waits for a completion interrupt via secure firmware. These observations establish a system-level stall, not a proven user-space MEMC root cause. The task name irqbalance alone does not establish causality. Firmware/IRQ routing and transition behavior require controlled comparison before changing kernel or device-tree code.

Earlier short stop/deinit failures and params-stream-off timeouts were affected by the test application's event-listening mode. With setListenStrmStatus(true), 20 short cycles passed using an isolated library build; after reset, the original board library also completed short cycles. This does not prove that rebuilding RKAIQ fixed the long-run stall.

No kernel, DDR frequency, GPIO, lane configuration, or firmware changes are included in these patches. The accepted AWB IQ is not changed or committed here.

## Validation notes

Release and ASan builds and all four tests passed. The new C++ regression fixture passes clang-format-14. Repository-wide format-check reports a pre-existing violation in src/ipc/posix_shared_memory.cpp:81 (`struct stat status{};`) on the unchanged main baseline; that unrelated file is not reformatted in this change.

The live board runs /usr/sbin/irqbalance --policyscript=/etc/irqbalance.d, whose policy sets balance_level=core for all IRQs. The freshly booted DMC IRQ is discovered by its action name (121 in this boot) and its affinity is CPU0. IRQ numbers are not stable between boots. These read-only observations are not proof of an affinity bug.

## Controlled rerun on the original board library

After a physical reset, the original board library v6.0x31.0 and event listening enabled completed another 9000-frame run: {'frames': 9000, 'contiguous': True, 'fps': 30.048076421417324, 'exit_status': 'CAP_RC=0\nAIQ_RC=0\n', 'stop_deinit': True, 'new_dmc_timeout_or_stall': False}

This run did not reproduce the system stall. It does not prove a firmware or IRQ fix, nor that the earlier failure cannot recur. The shutdown issue remains open; this PR intentionally contains no speculative kernel workaround.
