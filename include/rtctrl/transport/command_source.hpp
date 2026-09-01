#pragma once

#include "rtctrl/model/frames.hpp"

#include <cstdint>

namespace rtctrl::transport {

class ICommandSource {
public:
  virtual ~ICommandSource() = default;
  virtual bool poll(std::int64_t now_ns, model::ControlTarget& target) noexcept = 0;
};

}  // namespace rtctrl::transport

