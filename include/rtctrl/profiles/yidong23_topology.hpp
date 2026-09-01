#pragma once

#include "rtctrl/hal/motor_topology.hpp"

namespace rtctrl::profiles::yidong23 {

constexpr std::size_t kJointCount = 23;
using Topology = hal::MotorTopology<kJointCount, 3, 12>;

constexpr hal::MotorCalibration encos10020() {
  return {hal::MotorProtocol::Encos, 2.5, 1.0, -150.0, 150.0, 50.0};
}
constexpr hal::MotorCalibration encos8116() {
  return {hal::MotorProtocol::Encos, 2.35, 1.0, -150.0, 150.0, 5.0};
}
constexpr hal::MotorCalibration encos6408() {
  return {hal::MotorProtocol::Encos, 2.35, 1.0, -60.0, 60.0, 5.0};
}
constexpr hal::MotorCalibration encos4315() {
  return {hal::MotorProtocol::Encos, 2.8, 1.0, -70.0, 70.0, 5.0};
}
constexpr hal::MotorCalibration ti5_4052() {
  return {hal::MotorProtocol::Ti5, 0.05, 51.0, -8.3, 8.3, 5.0};
}
constexpr hal::MotorCalibration ti5_5060() {
  return {hal::MotorProtocol::Ti5, 0.089, 51.0, -23.0, 23.0, 5.0};
}
constexpr hal::MotorCalibration ti5_6070() {
  return {hal::MotorProtocol::Ti5, 0.092, 51.0, -42.0, 42.0, 5.0};
}

// Physical wiring and calibration distilled from the user's sx_text branch.
// Logical indices remain the stable API; EtherCAT master/slot and motor model
// are deployment data owned by this leaf profile.
constexpr Topology kTopology{
    {{{0, 0, 0, encos10020()}, {0, 1, 1, encos8116()},
      {0, 2, 2, encos6408()},  {0, 3, 3, encos10020()},
      {0, 4, 4, encos4315()},  {0, 5, 5, encos4315()},
      {0, 6, 6, encos10020()}, {0, 7, 7, encos8116()},
      {0, 8, 8, encos6408()},  {0, 9, 9, encos10020()},
      {0, 10, 10, encos4315()}, {0, 11, 11, encos4315()},
      {1, 0, 14, ti5_4052()},  {1, 1, 15, ti5_5060()},
      {1, 2, 16, ti5_5060()},  {1, 3, 17, ti5_4052()},
      {1, 4, 18, ti5_4052()},  {2, 0, 12, ti5_6070()},
      {2, 1, 20, ti5_5060()},  {2, 2, 22, ti5_4052()},
      {2, 3, 21, ti5_4052()},  {2, 4, 19, ti5_5060()},
      {2, 5, 13, ti5_6070()}}},
    {{12, 5, 6}},
    {{hal::MotorProtocol::Encos, hal::MotorProtocol::Ti5,
      hal::MotorProtocol::Ti5}}};

static_assert(kTopology.valid(),
              "Yidong profile must cover every physical slot and logical joint once");

constexpr std::size_t kLeftAnklePitch = 4;
constexpr std::size_t kLeftAnkleRoll = 5;
constexpr std::size_t kRightAnklePitch = 10;
constexpr std::size_t kRightAnkleRoll = 11;

}  // namespace rtctrl::profiles::yidong23
