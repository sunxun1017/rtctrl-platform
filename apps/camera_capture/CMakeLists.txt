cmake_minimum_required(VERSION 3.16)

# 允许我单独编译这个目录，也允许我被主目录包含
# 如果source directory等于当前源目录，那就说明单独编译的
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(camera_capture LANGUAGES CXX)
endif()

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(FATAL_ERROR "camera capture requires Linux V4L2")
endif()

add_executable(rtctrl_camera_capture
    main.cpp
)

target_compile_features(rtctrl_camera_capture PRIVATE cxx_std_17)

set_target_properties(rtctrl_camera_capture PROPERTIES
    CXX_EXTENSIONS OFF
)

target_compile_options(rtctrl_camera_capture PRIVATE
    -Wall
    -Wextra
    -Wpedantic
)

install(TARGETS rtctrl_camera_capture
    RUNTIME DESTINATION bin
)
