add_library(rtctrl_runtime realtime_engine.cpp)
target_link_libraries(rtctrl_runtime PUBLIC rtctrl_options rtctrl_platform rtctrl_hal
    rtctrl_control rtctrl_transport rtctrl_safety rtctrl_ipc Threads::Threads)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux" AND CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_link_libraries(rtctrl_runtime PUBLIC atomic)
endif()
