if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    add_executable(rtctrl_camera_test test_camera.c)
    target_link_libraries(rtctrl_camera_test PRIVATE rtctrl_vision_v4l2)
    target_link_options(rtctrl_camera_test PRIVATE
        -Wl,--wrap=open -Wl,--wrap=close -Wl,--wrap=mmap -Wl,--wrap=munmap
        -Wl,--wrap=poll -Wl,--wrap=__poll_chk -Wl,--wrap=ioctl)
    add_test(NAME rtctrl_camera_test COMMAND rtctrl_camera_test)
endif()
add_executable(rtctrl_v4l2_format_test test_v4l2_format.c)
target_include_directories(rtctrl_v4l2_format_test PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../src)
target_link_libraries(rtctrl_v4l2_format_test PRIVATE rtctrl_vision_v4l2)
add_test(NAME rtctrl_v4l2_format_test COMMAND rtctrl_v4l2_format_test)
