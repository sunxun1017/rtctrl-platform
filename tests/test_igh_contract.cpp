#include "rtctrl/ethercat/igh_master.hpp"

#include <cerrno>
#include <iostream>

int main() {
    using namespace rtctrl::ethercat;

    IghMasterConfig master{};
    if (valid_igh_configuration(master, nullptr, 0, nullptr, 0)) {
        std::cerr << "empty IgH configuration was accepted\n";
        return 1;
    }

    const PdoEntryMapping mapped_entry{0x6040, 0, 16};
    const PdoMapping pdo{0x1600, &mapped_entry, 1};
    const SyncManagerConfig sync{2, PdoDirection::Output, &pdo, 1, WatchdogMode::Enable};
    const std::uint8_t mode = 8;
    const StartupSdoConfig startup_sdo{0x6060, 0, &mode, sizeof(mode), false};
    const SlaveConfig slave{0, 0, 0x00000002, 0x12345678, &sync, 1, &startup_sdo, 1, {}};
    unsigned int offset = 0;
    const DomainEntryRegistration registration{0,      0, slave.vendor_id, slave.product_code,
                                               0x6040, 0, &offset,         nullptr};
    if (!valid_igh_configuration(master, &slave, 1, &registration, 1)) {
        std::cerr << "bounded IgH PDO configuration was rejected\n";
        return 1;
    }

    IghMaster bus(master);
    if (bus.activate(nullptr, 0, nullptr, 0) != IghStatus::InvalidConfig ||
        bus.last_error() != EINVAL) {
        std::cerr << "invalid IgH activation reached the native master API\n";
        return 1;
    }
    if (bus.receive(0) != IghStatus::NotReady || bus.last_error() != EAGAIN) {
        std::cerr << "inactive IgH cyclic call was not rejected\n";
        return 1;
    }
    IghBusState state{};
    state.expected_slaves = 1;
    state.slaves_responding = 1;
    state.link_up = true;
    state.all_slaves_online = true;
    state.all_slaves_operational = true;
    state.working_counter_state = WorkingCounterState::Complete;
    if (!state.ready()) {
        std::cerr << "complete EtherCAT health state was not considered ready\n";
        return 1;
    }
    state.working_counter_state = WorkingCounterState::Incomplete;
    if (state.ready()) {
        std::cerr << "incomplete EtherCAT working counter was considered ready\n";
        return 1;
    }
    std::cout << "IgH configuration contract passed\n";
    return 0;
}
