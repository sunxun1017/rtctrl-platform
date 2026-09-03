#include "rtctrl/ethercat/igh_master.hpp"

#include <ecrt.h>

#include <array>
#include <cerrno>
#include <limits>
#include <new>

namespace rtctrl::ethercat {
namespace {

static_assert(ECRT_VER_MAJOR == 1 && ECRT_VER_MINOR >= 6,
              "rtctrl IgH adapter requires the ecrt 1.6 API or newer");

int native_error(int result) noexcept {
  return result < 0 ? -result : (result > 0 ? result : EIO);
}

ec_direction_t native_direction(PdoDirection direction) noexcept {
  return direction == PdoDirection::Output ? EC_DIR_OUTPUT : EC_DIR_INPUT;
}

ec_watchdog_mode_t native_watchdog(WatchdogMode mode) noexcept {
  switch (mode) {
    case WatchdogMode::Enable: return EC_WD_ENABLE;
    case WatchdogMode::Disable: return EC_WD_DISABLE;
    case WatchdogMode::Default: return EC_WD_DEFAULT;
  }
  return EC_WD_DEFAULT;
}

bool valid_slave(const SlaveConfig& slave, std::size_t& sync_count,
                 std::size_t& pdo_count, std::size_t& mapped_entry_count,
                 std::size_t& startup_sdo_count, bool& has_dc) noexcept {
  if (slave.vendor_id == 0U || slave.product_code == 0U ||
      slave.sync_manager_count == 0U ||
      slave.sync_manager_count > EC_MAX_SYNC_MANAGERS ||
      slave.sync_managers == nullptr) {
    return false;
  }
  if (slave.startup_sdo_count != 0U && slave.startup_sdos == nullptr) {
    return false;
  }
  for (std::size_t i = 0; i < slave.startup_sdo_count; ++i) {
    const auto& sdo = slave.startup_sdos[i];
    if (startup_sdo_count == kIghMaxStartupSdos || sdo.index == 0U ||
        sdo.data == nullptr || sdo.size == 0U ||
        (sdo.complete_access && sdo.subindex != 0U)) {
      return false;
    }
    ++startup_sdo_count;
  }
  for (std::size_t sync_index = 0; sync_index < slave.sync_manager_count;
       ++sync_index) {
    const auto& sync = slave.sync_managers[sync_index];
    if (sync.index >= EC_MAX_SYNC_MANAGERS || sync.pdo_count == 0U ||
        sync.pdos == nullptr || sync_count == kIghMaxSyncManagers) {
      return false;
    }
    ++sync_count;
    for (std::size_t pdo_index = 0; pdo_index < sync.pdo_count; ++pdo_index) {
      const auto& pdo = sync.pdos[pdo_index];
      if (pdo.index == 0U || pdo.entry_count == 0U || pdo.entries == nullptr ||
          pdo_count == kIghMaxPdos) {
        return false;
      }
      ++pdo_count;
      for (std::size_t entry_index = 0; entry_index < pdo.entry_count;
           ++entry_index) {
        const auto& entry = pdo.entries[entry_index];
        if (entry.index == 0U || entry.bit_length == 0U ||
            mapped_entry_count == kIghMaxMappedEntries) {
          return false;
        }
        ++mapped_entry_count;
      }
    }
  }
  if (slave.distributed_clock.enabled) {
    if (slave.distributed_clock.assign_activate == 0U ||
        slave.distributed_clock.sync0_cycle_ns == 0U) {
      return false;
    }
    has_dc = true;
  }
  return true;
}

}  // namespace

struct IghMaster::Impl {
  ec_master_t* master{nullptr};
  ec_domain_t* domain{nullptr};
  std::array<ec_slave_config_t*, kIghMaxSlaves> slaves{};
  std::array<ec_sync_info_t, kIghMaxSyncManagers> syncs{};
  std::array<ec_pdo_info_t, kIghMaxPdos> pdos{};
  std::array<ec_pdo_entry_info_t, kIghMaxMappedEntries> mapped_entries{};
  std::array<ec_pdo_entry_reg_t, kIghMaxDomainEntries + 1U> registrations{};
};

bool valid_igh_configuration(const IghMasterConfig& master,
                             const SlaveConfig* slaves,
                             std::size_t slave_count,
                             const DomainEntryRegistration* entries,
                             std::size_t entry_count) noexcept {
  if (master.cycle_period_ns == 0U || slave_count == 0U ||
      slave_count > kIghMaxSlaves || slaves == nullptr || entry_count == 0U ||
      entry_count > kIghMaxDomainEntries || entries == nullptr) {
    return false;
  }
  std::size_t sync_count = 0;
  std::size_t pdo_count = 0;
  std::size_t mapped_entry_count = 0;
  std::size_t startup_sdo_count = 0;
  bool has_dc = false;
  for (std::size_t i = 0; i < slave_count; ++i) {
    if (!valid_slave(slaves[i], sync_count, pdo_count, mapped_entry_count,
                     startup_sdo_count, has_dc)) {
      return false;
    }
    for (std::size_t j = 0; j < i; ++j) {
      if (slaves[i].alias == slaves[j].alias &&
          slaves[i].position == slaves[j].position) {
        return false;
      }
    }
  }
  for (std::size_t i = 0; i < entry_count; ++i) {
    const auto& entry = entries[i];
    if (entry.vendor_id == 0U || entry.product_code == 0U || entry.index == 0U ||
        entry.byte_offset == nullptr) {
      return false;
    }
  }
  (void)has_dc;
  return true;
}

IghMaster::IghMaster(IghMasterConfig config) noexcept
    : config_(config), impl_(new (std::nothrow) Impl) {
  if (impl_ == nullptr) {
    last_error_ = ENOMEM;
  }
}

IghMaster::~IghMaster() {
  close();
  delete impl_;
}

IghStatus IghMaster::activate(const SlaveConfig* slaves,
                              std::size_t slave_count,
                              const DomainEntryRegistration* entries,
                              std::size_t entry_count) noexcept {
  if (active_ || impl_ == nullptr) {
    last_error_ = impl_ == nullptr ? ENOMEM : EALREADY;
    return IghStatus::NotReady;
  }
  if (!valid_igh_configuration(config_, slaves, slave_count, entries,
                               entry_count)) {
    last_error_ = EINVAL;
    return IghStatus::InvalidConfig;
  }

  impl_->master = ecrt_request_master(config_.master_index);
  if (impl_->master == nullptr) {
    last_error_ = errno == 0 ? ENODEV : errno;
    return IghStatus::IoError;
  }
  const auto interval_us = static_cast<std::size_t>(
      (static_cast<std::uint64_t>(config_.cycle_period_ns) + 999U) / 1000U);
  int result = ecrt_master_set_send_interval(impl_->master, interval_us);
  if (result != 0) {
    last_error_ = native_error(result);
    close();
    return IghStatus::IoError;
  }
  impl_->domain = ecrt_master_create_domain(impl_->master);
  if (impl_->domain == nullptr) {
    last_error_ = errno == 0 ? EIO : errno;
    close();
    return IghStatus::IoError;
  }

  std::size_t next_sync = 0;
  std::size_t next_pdo = 0;
  std::size_t next_mapping = 0;
  ec_slave_config_t* dc_reference = nullptr;
  for (std::size_t slave_index = 0; slave_index < slave_count; ++slave_index) {
    const auto& slave = slaves[slave_index];
    auto* native_slave = ecrt_master_slave_config(
        impl_->master, slave.alias, slave.position, slave.vendor_id,
        slave.product_code);
    if (native_slave == nullptr) {
      last_error_ = errno == 0 ? ENODEV : errno;
      close();
      return IghStatus::IoError;
    }
    impl_->slaves[slave_index] = native_slave;

    const std::size_t slave_sync_begin = next_sync;
    for (std::size_t sync_index = 0;
         sync_index < slave.sync_manager_count; ++sync_index) {
      const auto& sync = slave.sync_managers[sync_index];
      const std::size_t sync_pdo_begin = next_pdo;
      for (std::size_t pdo_index = 0; pdo_index < sync.pdo_count; ++pdo_index) {
        const auto& pdo = sync.pdos[pdo_index];
        const std::size_t pdo_entry_begin = next_mapping;
        for (std::size_t entry_index = 0; entry_index < pdo.entry_count;
             ++entry_index) {
          const auto& entry = pdo.entries[entry_index];
          impl_->mapped_entries[next_mapping++] =
              {entry.index, entry.subindex, entry.bit_length};
        }
        impl_->pdos[next_pdo++] =
            {pdo.index, static_cast<unsigned int>(pdo.entry_count),
             &impl_->mapped_entries[pdo_entry_begin]};
      }
      impl_->syncs[next_sync++] = {
          sync.index, native_direction(sync.direction),
          static_cast<unsigned int>(sync.pdo_count),
          &impl_->pdos[sync_pdo_begin], native_watchdog(sync.watchdog)};
    }
    result = ecrt_slave_config_pdos(
        native_slave, static_cast<unsigned int>(slave.sync_manager_count),
        &impl_->syncs[slave_sync_begin]);
    if (result != 0) {
      last_error_ = native_error(result);
      close();
      return IghStatus::IoError;
    }
    for (std::size_t sdo_index = 0; sdo_index < slave.startup_sdo_count;
         ++sdo_index) {
      const auto& sdo = slave.startup_sdos[sdo_index];
      result = sdo.complete_access
                   ? ecrt_slave_config_complete_sdo(native_slave, sdo.index,
                                                    sdo.data, sdo.size)
                   : ecrt_slave_config_sdo(native_slave, sdo.index,
                                           sdo.subindex, sdo.data, sdo.size);
      if (result != 0) {
        last_error_ = native_error(result);
        close();
        return IghStatus::IoError;
      }
    }
    if (slave.distributed_clock.enabled) {
      const auto& dc = slave.distributed_clock;
      result = ecrt_slave_config_dc(native_slave, dc.assign_activate,
                                    dc.sync0_cycle_ns, dc.sync0_shift_ns,
                                    dc.sync1_cycle_ns, dc.sync1_shift_ns);
      if (result != 0) {
        last_error_ = native_error(result);
        close();
        return IghStatus::IoError;
      }
      if (dc_reference == nullptr) {
        dc_reference = native_slave;
      }
      dc_enabled_ = true;
    }
  }

  if (dc_reference != nullptr) {
    result = ecrt_master_select_reference_clock(impl_->master, dc_reference);
    if (result != 0) {
      last_error_ = native_error(result);
      close();
      return IghStatus::IoError;
    }
  }

  for (std::size_t i = 0; i < entry_count; ++i) {
    const auto& entry = entries[i];
    impl_->registrations[i] =
        {entry.alias, entry.position, entry.vendor_id, entry.product_code,
         entry.index, entry.subindex, entry.byte_offset, entry.bit_position};
  }
  impl_->registrations[entry_count] = {};
  result = ecrt_domain_reg_pdo_entry_list(impl_->domain,
                                          impl_->registrations.data());
  if (result != 0) {
    last_error_ = native_error(result);
    close();
    return IghStatus::IoError;
  }
  result = ecrt_master_activate(impl_->master);
  if (result != 0) {
    last_error_ = native_error(result);
    close();
    return IghStatus::IoError;
  }
  process_data_ = ecrt_domain_data(impl_->domain);
  process_data_size_ = ecrt_domain_size(impl_->domain);
  if (process_data_ == nullptr || process_data_size_ == 0U) {
    last_error_ = EIO;
    close();
    return IghStatus::IoError;
  }

  slave_count_ = slave_count;
  state_ = {};
  state_.expected_slaves = static_cast<unsigned int>(slave_count);
  cycle_count_ = 0;
  cycle_received_ = false;
  active_ = true;
  last_error_ = 0;
  return IghStatus::Ok;
}

IghStatus IghMaster::receive(std::uint64_t application_time_ns) noexcept {
  if (!active_ || impl_ == nullptr || cycle_received_) {
    last_error_ = EAGAIN;
    return IghStatus::NotReady;
  }
  int result = ecrt_master_receive(impl_->master);
  if (result != 0) {
    last_error_ = native_error(result);
    return IghStatus::IoError;
  }
  result = ecrt_domain_process(impl_->domain);
  if (result != 0) {
    last_error_ = native_error(result);
    return IghStatus::IoError;
  }
  result = ecrt_master_application_time(impl_->master, application_time_ns);
  if (result != 0) {
    last_error_ = native_error(result);
    return IghStatus::IoError;
  }

  ec_master_state_t master_state{};
  ec_domain_state_t domain_state{};
  if (ecrt_master_state(impl_->master, &master_state) != 0 ||
      ecrt_domain_state(impl_->domain, &domain_state) != 0) {
    last_error_ = EIO;
    return IghStatus::IoError;
  }
  state_.slaves_responding = master_state.slaves_responding;
  state_.link_up = master_state.link_up != 0U;
  state_.al_states = static_cast<std::uint8_t>(master_state.al_states);
  state_.working_counter = domain_state.working_counter;
  switch (domain_state.wc_state) {
    case EC_WC_COMPLETE:
      state_.working_counter_state = WorkingCounterState::Complete;
      break;
    case EC_WC_INCOMPLETE:
      state_.working_counter_state = WorkingCounterState::Incomplete;
      break;
    case EC_WC_ZERO:
    default:
      state_.working_counter_state = WorkingCounterState::Zero;
      break;
  }
  state_.all_slaves_online = true;
  state_.all_slaves_operational = true;
  for (std::size_t i = 0; i < slave_count_; ++i) {
    ec_slave_config_state_t slave_state{};
    if (ecrt_slave_config_state(impl_->slaves[i], &slave_state) != 0) {
      last_error_ = EIO;
      return IghStatus::IoError;
    }
    state_.all_slaves_online =
        state_.all_slaves_online && slave_state.online != 0U;
    state_.all_slaves_operational =
        state_.all_slaves_operational && slave_state.operational != 0U;
  }
  cycle_received_ = true;
  last_error_ = 0;
  return IghStatus::Ok;
}

IghStatus IghMaster::send() noexcept {
  if (!active_ || impl_ == nullptr || !cycle_received_) {
    last_error_ = EAGAIN;
    return IghStatus::NotReady;
  }
  int result = ecrt_domain_queue(impl_->domain);
  if (result != 0) {
    last_error_ = native_error(result);
    return IghStatus::IoError;
  }
  if (dc_enabled_) {
    if (config_.reference_sync_interval_cycles != 0U &&
        cycle_count_ % config_.reference_sync_interval_cycles == 0U) {
      result = ecrt_master_sync_reference_clock(impl_->master);
      if (result != 0) {
        last_error_ = native_error(result);
        return IghStatus::IoError;
      }
    }
    result = ecrt_master_sync_slave_clocks(impl_->master);
    if (result != 0) {
      last_error_ = native_error(result);
      return IghStatus::IoError;
    }
  }
  result = ecrt_master_send(impl_->master);
  if (result != 0) {
    last_error_ = native_error(result);
    return IghStatus::IoError;
  }
  ++cycle_count_;
  cycle_received_ = false;
  last_error_ = 0;
  return IghStatus::Ok;
}

void IghMaster::close() noexcept {
  active_ = false;
  cycle_received_ = false;
  process_data_ = nullptr;
  process_data_size_ = 0;
  slave_count_ = 0;
  dc_enabled_ = false;
  state_ = {};
  if (impl_ != nullptr && impl_->master != nullptr) {
    ecrt_release_master(impl_->master);
  }
  if (impl_ != nullptr) {
    impl_->master = nullptr;
    impl_->domain = nullptr;
    impl_->slaves.fill(nullptr);
  }
}

}  // namespace rtctrl::ethercat
