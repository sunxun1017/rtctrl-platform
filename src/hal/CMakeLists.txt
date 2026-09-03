add_library(rtctrl_hal
    dynamixel_protocol.cpp simulated_hal.cpp shared_memory_hal.cpp kernel_mailbox_hal.cpp
    half_duplex_serial_link.cpp protocol_actuator_hal.cpp)
target_link_libraries(rtctrl_hal PUBLIC rtctrl_options rtctrl_ipc rtctrl_protocol)
