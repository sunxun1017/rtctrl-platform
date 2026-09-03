cmake_minimum_required(VERSION 3.16)
project(rtctrl_platform VERSION 0.5.0 LANGUAGES C CXX)

option(RTCTRL_ENABLE_SANITIZERS "Enable address and undefined-behavior sanitizers" OFF)
option(RTCTRL_ENABLE_TSAN "Enable thread sanitizer" OFF)
option(RTCTRL_BUILD_TESTS "Build unit tests" ON)
option(RTCTRL_ENABLE_IGH_ETHERCAT "Build the optional IgH EtherCAT ecrt adapter" OFF)
option(RTCTRL_ENABLE_FORMAT_TARGETS "Add clang-format check and rewrite targets" ON)
set(RTCTRL_IGH_ROOT "" CACHE PATH "IgH EtherCAT installation prefix")
set(RTCTRL_JOINT_COUNT 6 CACHE STRING "Compile-time logical joint count (1..64)")

# Preserve the original flat artifact layout after moving targets into subdirectories.
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY "${PROJECT_BINARY_DIR}")
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${PROJECT_BINARY_DIR}")
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${PROJECT_BINARY_DIR}")

find_package(Threads REQUIRED)
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)
include(cmake/BuildOptions.cmake)
include(cmake/Formatting.cmake)

rtctrl_add_build_options()
rtctrl_add_format_targets()

add_subdirectory(src/platform)
add_subdirectory(src/ipc)
add_subdirectory(src/protocol)
add_subdirectory(src/hal)
add_subdirectory(src/control)
add_subdirectory(src/transport)
add_subdirectory(src/safety)
add_subdirectory(src/runtime)

if(RTCTRL_ENABLE_IGH_ETHERCAT)
    add_subdirectory(src/ethercat)
endif()

add_library(rtctrl INTERFACE)
target_link_libraries(rtctrl INTERFACE rtctrl_runtime)

add_subdirectory(apps)

if(RTCTRL_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()

include(cmake/Install.cmake)
