rtctrl_adapter(rtctrl_capture_synthetic src/synthetic_capture.c)
target_link_libraries(rtctrl_capture_synthetic PUBLIC rtctrl_capture)
target_compile_options(rtctrl_capture_synthetic PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)
