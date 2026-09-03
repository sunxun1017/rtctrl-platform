#include "rtctrl/platform/posix_realtime.hpp"

#include <cerrno>
#include <cstddef>
#include <ctime>
#include <pthread.h>
#include <sched.h>
#include <sys/mman.h>
#include <unistd.h>

namespace rtctrl::platform {
namespace {

timespec to_timespec(std::int64_t nanoseconds) noexcept {
    timespec value{};
    value.tv_sec = static_cast<time_t>(nanoseconds / 1'000'000'000LL);
    value.tv_nsec = static_cast<long>(nanoseconds % 1'000'000'000LL);
    return value;
}

} // namespace

std::int64_t PosixRealtimePlatform::now_ns() const noexcept {
    timespec value{};
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) {
        return 0;
    }
    return static_cast<std::int64_t>(value.tv_sec) * 1'000'000'000LL + value.tv_nsec;
}

MemoryLockReport PosixRealtimePlatform::lock_process_memory() noexcept {
    MemoryLockReport report{};
    if (mlockall(MCL_CURRENT | MCL_FUTURE) == 0) {
        report.active = true;
    } else {
        report.error = errno;
    }
    return report;
}

ThreadSetupReport
PosixRealtimePlatform::configure_current_thread(const ThreadConfig& config) noexcept {
    ThreadSetupReport report{};
    if (config.name != nullptr) {
        (void)pthread_setname_np(pthread_self(), config.name);
    }

    if (config.cpu >= 0) {
        const long cpu_count = sysconf(_SC_NPROCESSORS_CONF);
        if (config.cpu >= CPU_SETSIZE || cpu_count <= 0 || config.cpu >= cpu_count) {
            report.affinity_error = EINVAL;
            return report;
        }
        cpu_set_t set;
        CPU_ZERO(&set);
        CPU_SET(static_cast<unsigned>(config.cpu), &set);
        report.affinity_error = pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
        report.affinity_active = report.affinity_error == 0;
    } else {
        report.affinity_active = true;
    }

    if (config.priority > 0) {
        sched_param parameter{};
        parameter.sched_priority = config.priority;
        report.scheduler_error = pthread_setschedparam(pthread_self(), SCHED_FIFO, &parameter);
        report.fifo_active = report.scheduler_error == 0;
    } else {
        report.fifo_active = false;
    }
    return report;
}

void PosixRealtimePlatform::prefault_stack() noexcept {
    volatile unsigned char
        buffer[64 * 1024]{}; // TODO: make sure target system stack size is at least 64kB, or use
                             // pthread_attr_getstacksize() to get the actual stack size
    constexpr std::size_t kPageSize = 4096; // TODO: make sure target system page size is 4kB, or
                                            // use sysconf(_SC_PAGESIZE) to get the actual page size
    for (std::size_t i = 0; i < sizeof(buffer); i += kPageSize) {
        buffer[i] = 0;
    }
}

int PosixRealtimePlatform::sleep_until(std::int64_t absolute_deadline_ns) noexcept {
    auto deadline = to_timespec(absolute_deadline_ns);
    int result = 0;
    do {
        result = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &deadline, nullptr);
    } while (result == EINTR);
    return result;
}

} // namespace rtctrl::platform
