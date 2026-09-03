#pragma once

#include <cstddef>
#include <cstdint>

namespace rtctrl::ethercat {

constexpr std::size_t kIghMaxSlaves = 64;
constexpr std::size_t kIghMaxSyncManagers = 256;
constexpr std::size_t kIghMaxPdos = 512;
constexpr std::size_t kIghMaxMappedEntries = 2048;
constexpr std::size_t kIghMaxDomainEntries = 2048;
constexpr std::size_t kIghMaxStartupSdos = 1024;

enum class PdoDirection : std::uint8_t { Output, Input };
enum class WatchdogMode : std::uint8_t { Default, Enable, Disable };
enum class WorkingCounterState : std::uint8_t { Zero, Incomplete, Complete };
enum class IghStatus : std::uint8_t { Ok, NotReady, InvalidConfig, IoError };

struct PdoEntryMapping {
  std::uint16_t index{0};
  std::uint8_t subindex{0};
  std::uint8_t bit_length{0};
};

struct PdoMapping {
  std::uint16_t index{0};
  const PdoEntryMapping* entries{nullptr};
  std::size_t entry_count{0};
};

struct SyncManagerConfig {
  std::uint8_t index{0};
  PdoDirection direction{PdoDirection::Input};
  const PdoMapping* pdos{nullptr};
  std::size_t pdo_count{0};
  WatchdogMode watchdog{WatchdogMode::Default};
};

struct DistributedClockConfig {
  bool enabled{false};
  std::uint16_t assign_activate{0};
  std::uint32_t sync0_cycle_ns{0};
  std::int32_t sync0_shift_ns{0};
  std::uint32_t sync1_cycle_ns{0};
  std::int32_t sync1_shift_ns{0};
};

struct StartupSdoConfig {
  std::uint16_t index{0};
  std::uint8_t subindex{0};
  const std::uint8_t* data{nullptr};
  std::size_t size{0};
  bool complete_access{false};
};

struct SlaveConfig {
  std::uint16_t alias{0};
  std::uint16_t position{0};
  std::uint32_t vendor_id{0};
  std::uint32_t product_code{0};
  const SyncManagerConfig* sync_managers{nullptr};
  std::size_t sync_manager_count{0};
  const StartupSdoConfig* startup_sdos{nullptr};
  std::size_t startup_sdo_count{0};
  DistributedClockConfig distributed_clock{};
};

struct DomainEntryRegistration {
  std::uint16_t alias{0};
  std::uint16_t position{0};
  std::uint32_t vendor_id{0};
  std::uint32_t product_code{0};
  std::uint16_t index{0};
  std::uint8_t subindex{0};
  unsigned int* byte_offset{nullptr};
  unsigned int* bit_position{nullptr};
};

struct IghMasterConfig {
  unsigned int master_index{0};
  std::uint32_t cycle_period_ns{1'000'000};
  // Zero disables reference-clock drift compensation. Slave-clock
  // compensation still runs every cycle when DC is configured.
  std::uint32_t reference_sync_interval_cycles{10};
};

struct IghBusState {
  unsigned int slaves_responding{0};
  unsigned int expected_slaves{0};
  unsigned int working_counter{0};
  std::uint8_t al_states{0};
  WorkingCounterState working_counter_state{WorkingCounterState::Zero};
  bool link_up{false};
  bool all_slaves_online{false};
  bool all_slaves_operational{false};

  bool ready() const noexcept {
    return link_up && slaves_responding == expected_slaves &&
           working_counter_state == WorkingCounterState::Complete &&
           all_slaves_online && all_slaves_operational;
  }
};

bool valid_igh_configuration(const IghMasterConfig& master,
                             const SlaveConfig* slaves,
                             std::size_t slave_count,
                             const DomainEntryRegistration* entries,
                             std::size_t entry_count) noexcept;

// Generic IgH ecrt master/domain owner. Configuration and close() are
// non-realtime operations. receive() and send() are the bounded cyclic path.
// Device control words, PDO values, units and safe-stop semantics remain in a
// device-specific L0 adapter operating on process_data().
class IghMaster final {
public:
  explicit IghMaster(IghMasterConfig config = {}) noexcept;
  ~IghMaster();

  IghMaster(const IghMaster&) = delete;
  IghMaster& operator=(const IghMaster&) = delete;
  IghMaster(IghMaster&&) = delete;
  IghMaster& operator=(IghMaster&&) = delete;

  IghStatus activate(const SlaveConfig* slaves, std::size_t slave_count,
                     const DomainEntryRegistration* entries,
                     std::size_t entry_count) noexcept;
  IghStatus receive(std::uint64_t application_time_ns) noexcept;
  IghStatus send() noexcept;
  void close() noexcept;

  std::uint8_t* process_data() noexcept { return process_data_; }
  const std::uint8_t* process_data() const noexcept { return process_data_; }
  std::size_t process_data_size() const noexcept { return process_data_size_; }
  const IghBusState& state() const noexcept { return state_; }
  int last_error() const noexcept { return last_error_; }
  bool active() const noexcept { return active_; }

private:
  struct Impl;

  IghMasterConfig config_{};
  Impl* impl_{nullptr};
  std::uint8_t* process_data_{nullptr};
  std::size_t process_data_size_{0};
  IghBusState state_{};
  std::size_t slave_count_{0};
  std::uint64_t cycle_count_{0};
  int last_error_{0};
  bool dc_enabled_{false};
  bool active_{false};
  bool cycle_received_{false};
};

}  // namespace rtctrl::ethercat
