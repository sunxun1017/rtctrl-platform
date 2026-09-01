#include "rtctrl/runtime/realtime_engine.hpp"

#include <chrono>
#include <exception>
#include <thread>

namespace rtctrl::runtime {
namespace {

bool setup_failed(const platform::ThreadConfig& config,
                  const platform::ThreadSetupReport& report) noexcept {
  if (!config.strict) {
    return false;
  }
  const bool affinity_failed = config.cpu >= 0 && !report.affinity_active;
  const bool scheduler_failed = config.priority > 0 && !report.fifo_active;
  return affinity_failed || scheduler_failed;
}

bool valid_config(const RuntimeConfig& config) noexcept {
  const bool periods_valid = config.io_period_ns > 0 && config.control_period_ns > 0 &&
                             config.source_period_ns > 0 &&
                             config.control_period_ns % config.io_period_ns == 0;
  const bool leases_valid = config.command_validity_ns >= config.control_period_ns &&
                            config.target_validity_ns >= config.source_period_ns &&
                            config.state_validity_ns >= config.control_period_ns;
  const auto valid_thread = [](const platform::ThreadConfig& value) {
    return value.priority >= 0 && value.priority <= 99 && value.cpu >= -1;
  };
  return periods_valid && leases_valid && valid_thread(config.io_thread) &&
         valid_thread(config.control_thread);
}

bool wait_for_startup(const std::atomic<int>& state) noexcept {
  for (int attempt = 0; attempt < 1000; ++attempt) {
    if (state.load(std::memory_order_acquire) != 0) {
      return state.load(std::memory_order_acquire) > 0;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  return false;
}

}  // namespace

RealtimeEngine::RealtimeEngine(RuntimeConfig config, platform::IRealtimePlatform& platform,
                               hal::IActuatorHal& hal,
                               control::IController& controller,
                               transport::ICommandSource& source,
                               safety::SafetyPolicy& safety) noexcept
    : config_(config),
      platform_(platform),
      hal_(hal),
      controller_(controller),
      source_(source),
      safety_(safety) {}

RealtimeEngine::~RealtimeEngine() {
  request_stop();
  join();
}

bool RealtimeEngine::start() noexcept {
  if (running_.exchange(true) || started_once_ || !valid_config(config_)) {
    running_.store(false);
    return false;
  }
  started_once_ = true;
  stop_.store(false);
  fatal_startup_error_.store(false);
  io_startup_state_.store(0);
  control_startup_state_.store(0);
  report_ = {};
  if (config_.lock_memory) {
    report_.memory = platform_.lock_process_memory();
    if (!report_.memory.active && (config_.io_thread.strict || config_.control_thread.strict)) {
      report_.fatal_startup_error = true;
      running_.store(false);
      return false;
    }
  }

  try {
    io_thread_ = std::thread(&RealtimeEngine::io_loop, this);
    control_thread_ = std::thread(&RealtimeEngine::control_loop, this);
    if (!wait_for_startup(io_startup_state_) || !wait_for_startup(control_startup_state_)) {
      stop_.store(true);
      join();
      return false;
    }
    source_thread_ = std::thread(&RealtimeEngine::source_loop, this);
  } catch (const std::exception&) {
    stop_.store(true);
    join();
    hal_.emergency_stop(platform_.now_ns());
    hal_.close();
    return false;
  }
  return true;
}

void RealtimeEngine::request_stop() noexcept { stop_.store(true, std::memory_order_release); }

void RealtimeEngine::join() noexcept {
  if (source_thread_.joinable()) {
    source_thread_.join();
  }
  if (control_thread_.joinable()) {
    control_thread_.join();
  }
  if (io_thread_.joinable()) {
    io_thread_.join();
  }
  report_.fatal_startup_error = fatal_startup_error_.load();
  running_.store(false);
}

RuntimeReport RealtimeEngine::report() const noexcept {
  if (running_.load(std::memory_order_acquire)) {
    return {};
  }
  return report_;
}

void RealtimeEngine::io_loop() noexcept {
  platform_.prefault_stack();
  report_.io_setup = platform_.configure_current_thread(config_.io_thread);
  if (setup_failed(config_.io_thread, report_.io_setup)) {
    fatal_startup_error_.store(true);
    io_startup_state_.store(-1, std::memory_order_release);
    stop_.store(true);
    return;
  }
  if (hal_.open_safe(platform_.now_ns()) != hal::HalStatus::Ok) {
    fatal_startup_error_.store(true);
    io_startup_state_.store(-1, std::memory_order_release);
    stop_.store(true);
    hal_.emergency_stop(platform_.now_ns());
    hal_.close();
    return;
  }
  model::SensorFrame startup_state{};
  if (config_.arm_actuation &&
      (hal_.read(platform_.now_ns(), startup_state) != hal::HalStatus::Ok ||
       hal_.arm(platform_.now_ns()) != hal::HalStatus::Ok)) {
    fatal_startup_error_.store(true);
    io_startup_state_.store(-1, std::memory_order_release);
    stop_.store(true);
    hal_.emergency_stop(platform_.now_ns());
    hal_.close();
    return;
  }
  io_startup_state_.store(1, std::memory_order_release);

  platform::PeriodicTimer timer(platform_, config_.io_period_ns);
  model::SensorFrame state{};
  if (config_.arm_actuation) {
    state = startup_state;
  }
  model::CommandFrame command{};
  safety_.make_safe_command(state, platform_.now_ns(), command);
  bool fault_latched = false;
  bool hardware_safe_state_entered = false;
  hardware_safe_state_entered = !config_.arm_actuation;

  while (!stop_.load(std::memory_order_acquire)) {
    const auto wakeup = timer.wait_next();
    if (wakeup.wait_error != 0) {
      ++report_.io_metrics.io_errors;
      fatal_startup_error_.store(true);
      stop_.store(true);
      break;
    }
    const auto begin_ns = platform_.now_ns();
    report_.io_metrics.record_wakeup(wakeup.actual_ns - wakeup.scheduled_ns,
                                     wakeup.skipped_periods);

    const bool read_ok = hal_.read(begin_ns, state) == hal::HalStatus::Ok;
    if (!read_ok) {
      ++report_.io_metrics.io_errors;
      if (!fault_latched) {
        ++report_.safety_interventions;
      }
      fault_latched = true;
      report_.fault_latched = true;
    }
    if (read_ok && !states_.try_push(state)) {
      ++report_.io_metrics.queue_drops;
    }

    model::CommandFrame candidate{};
    if (commands_.drain_latest(candidate)) {
      command = candidate;
    }

    if (fault_latched) {
      if (!hardware_safe_state_entered) {
        hal_.emergency_stop(begin_ns);
        hardware_safe_state_entered = true;
      }
      report_.io_metrics.record_execution(platform_.now_ns() - begin_ns);
      continue;
    }
    if (!config_.arm_actuation) {
      report_.io_metrics.record_execution(platform_.now_ns() - begin_ns);
      continue;
    }

    const auto decision = safety_.evaluate(state, command, begin_ns);
    if (decision != safety::SafetyDecision::Accept) {
      if (decision == safety::SafetyDecision::CommandExpired) {
        ++report_.io_metrics.stale_commands;
      }
      ++report_.safety_interventions;
      if (decision == safety::SafetyDecision::HardwareFault ||
          decision == safety::SafetyDecision::InvalidNumber ||
          decision == safety::SafetyDecision::LimitViolation) {
        fault_latched = true;
        report_.fault_latched = true;
        if (!hardware_safe_state_entered) {
          hal_.emergency_stop(begin_ns);
          hardware_safe_state_entered = true;
        }
        report_.io_metrics.record_execution(platform_.now_ns() - begin_ns);
        continue;
      }
      safety_.make_safe_command(state, begin_ns, command);
    }

    if (hal_.write(begin_ns, command) != hal::HalStatus::Ok) {
      ++report_.io_metrics.io_errors;
      fault_latched = true;
      report_.fault_latched = true;
      ++report_.safety_interventions;
      if (!hardware_safe_state_entered) {
        hal_.emergency_stop(begin_ns);
        hardware_safe_state_entered = true;
      }
    }
    report_.io_metrics.record_execution(platform_.now_ns() - begin_ns);
  }

  if (!hardware_safe_state_entered) {
    hal_.emergency_stop(platform_.now_ns());
  }
  hal_.close();
}

void RealtimeEngine::control_loop() noexcept {
  platform_.prefault_stack();
  report_.control_setup = platform_.configure_current_thread(config_.control_thread);
  if (setup_failed(config_.control_thread, report_.control_setup)) {
    fatal_startup_error_.store(true);
    control_startup_state_.store(-1, std::memory_order_release);
    stop_.store(true);
    return;
  }
  control_startup_state_.store(1, std::memory_order_release);

  platform::PeriodicTimer timer(platform_, config_.control_period_ns);
  model::SensorFrame state{};
  model::ControlTarget target{};
  bool initialized = false;
  bool has_target = false;
  std::uint64_t last_target_sequence = 0;
  std::uint64_t last_state_sequence = 0;

  while (!stop_.load(std::memory_order_acquire)) {
    const auto wakeup = timer.wait_next();
    if (wakeup.wait_error != 0) {
      ++report_.control_metrics.io_errors;
      fatal_startup_error_.store(true);
      stop_.store(true);
      break;
    }
    const auto begin_ns = platform_.now_ns();
    report_.control_metrics.record_wakeup(wakeup.actual_ns - wakeup.scheduled_ns,
                                          wakeup.skipped_periods);
    model::ControlTarget candidate_target{};
    if (targets_.drain_latest(candidate_target) &&
        candidate_target.sequence > last_target_sequence &&
        candidate_target.created_time_ns <= begin_ns + config_.control_period_ns) {
      target = candidate_target;
      last_target_sequence = target.sequence;
      has_target = true;
    }
    if (!states_.drain_latest(state)) {
      report_.control_metrics.record_execution(platform_.now_ns() - begin_ns);
      continue;
    }
    const bool state_fresh = state.sequence > last_state_sequence && state.sample_time_ns <= begin_ns &&
                             begin_ns - state.sample_time_ns <= config_.state_validity_ns;
    last_state_sequence = state.sequence;
    const bool transport_lease_fresh =
        target.valid_until_ns == 0 ||
        (target.valid_until_ns >= target.created_time_ns && begin_ns <= target.valid_until_ns);
    const bool target_fresh = has_target && target.created_time_ns <= begin_ns &&
                              begin_ns - target.created_time_ns <= config_.target_validity_ns &&
                              transport_lease_fresh;
    if (!state_fresh || !target_fresh) {
      report_.control_metrics.record_execution(platform_.now_ns() - begin_ns);
      continue;
    }
    if (!initialized) {
      controller_.reset(state);
      initialized = true;
    }

    control::ControlContext context{};
    context.now_ns = begin_ns;
    context.command_validity_ns = config_.command_validity_ns;
    context.dt_seconds = static_cast<double>(config_.control_period_ns) / 1.0e9;
    context.target = target;
    model::CommandFrame command{};
    if (controller_.update(state, context, command) && !commands_.try_push(command)) {
      ++report_.control_metrics.queue_drops;
    }
    report_.control_metrics.record_execution(platform_.now_ns() - begin_ns);
  }
}

void RealtimeEngine::source_loop() noexcept {
  platform::PeriodicTimer timer(platform_, config_.source_period_ns);
  while (!stop_.load(std::memory_order_acquire)) {
    const auto wakeup = timer.wait_next();
    if (wakeup.wait_error != 0) {
      fatal_startup_error_.store(true);
      stop_.store(true);
      break;
    }
    model::ControlTarget target{};
    if (source_.poll(wakeup.actual_ns, target)) {
      if (!targets_.try_push(target)) {
        ++report_.control_metrics.queue_drops;
      }
    }
  }
}

}  // namespace rtctrl::runtime
