rtctrl_adapter(rtctrl_vision_v4l2 src/v4l2_capture.c src/v4l2_format.c)
target_link_libraries(rtctrl_vision_v4l2 PUBLIC rtctrl_capture)
target_compile_options(rtctrl_vision_v4l2 PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)
