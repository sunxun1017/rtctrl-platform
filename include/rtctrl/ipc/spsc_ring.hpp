#pragma once

#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace rtctrl::ipc {

template <typename T, std::size_t Capacity> class SpscRing {
  static_assert(Capacity >= 2 && (Capacity & (Capacity - 1)) == 0,
                "capacity must be a power of two");
  static_assert(std::is_trivially_copyable_v<T>, "real-time messages must be POD-like");
  static_assert(std::atomic<std::uint64_t>::is_always_lock_free,
                "SPSC counters must be lock-free on the target platform");

public:
  bool try_push(const T& value) noexcept {
    const auto head = head_.value.load(std::memory_order_relaxed);
    const auto tail = tail_.value.load(std::memory_order_acquire);
    if (head - tail == Capacity) {
      return false;
    }
    storage_[head & (Capacity - 1)] = value;
    head_.value.store(head + 1, std::memory_order_release);
    return true;
  }

  bool try_pop(T& value) noexcept {
    const auto tail = tail_.value.load(std::memory_order_relaxed);
    const auto head = head_.value.load(std::memory_order_acquire);
    if (tail == head) {
      return false;
    }
    value = storage_[tail & (Capacity - 1)];
    tail_.value.store(tail + 1, std::memory_order_release);
    return true;
  }

  bool drain_latest(T& value) noexcept {
    bool found = false;
    T candidate{};
    while (try_pop(candidate)) {
      value = candidate;
      found = true;
    }
    return found;
  }

  std::size_t size_approx() const noexcept {
    const auto tail = tail_.value.load(std::memory_order_acquire);
    const auto head = head_.value.load(std::memory_order_acquire);
    if (head < tail) {
      return 0;
    }
    const auto distance = head - tail;
    return static_cast<std::size_t>(distance > Capacity ? Capacity : distance);
  }

private:
  struct alignas(64) Counter {
    std::atomic<std::uint64_t> value{0};
  };

  std::array<T, Capacity> storage_{};
  Counter head_{};
  Counter tail_{};
};

}  // namespace rtctrl::ipc
