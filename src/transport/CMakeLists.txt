add_library(rtctrl_transport
    loopback_source.cpp loopback_byte_transport.cpp framed_command_source.cpp
    posix_serial_transport.cpp socketcan_fd_transport.cpp)
target_link_libraries(rtctrl_transport PUBLIC rtctrl_options rtctrl_protocol)
