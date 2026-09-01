#pragma once

#include "rtctrl/model/frames.hpp"

#include <cstdint>

namespace rtctrl::control {

struct ControlContext {
  std::int64_t now_ns{0};
  std::int64_t command_validity_ns{0};
  double dt_seconds{0.0};
  model::ControlTarget target{};
};

class IController {
public:
  virtual ~IController() = default;
  virtual void reset(const model::SensorFrame& state) noexcept = 0;
  virtual bool update(const model::SensorFrame& state, const ControlContext& context,
                      model::CommandFrame& command) noexcept = 0;
};

}  // namespace rtctrl::control

