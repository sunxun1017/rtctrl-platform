add_library(rtctrl_platform realtime_platform.cpp posix_realtime.cpp)
target_link_libraries(rtctrl_platform PUBLIC rtctrl_options Threads::Threads)
