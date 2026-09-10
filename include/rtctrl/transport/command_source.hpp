#pragma once
#include "rtctrl/bridge/command_source.hpp"

namespace rtctrl::transport {
// Compatibility name; semantic input belongs to the application boundary.
using ICommandSource = bridge::ICommandSource;
} // namespace rtctrl::transport
