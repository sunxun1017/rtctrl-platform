cmake_minimum_required(VERSION 3.16)
project(rtctrl_platform VERSION 0.7.0 LANGUAGES C CXX)

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

set(RTCTRL_PRODUCT "development" CACHE STRING "development, control-sim, vision-node, robot-vision")
set_property(CACHE RTCTRL_PRODUCT PROPERTY STRINGS development control-sim vision-node robot-vision)
if(NOT RTCTRL_PRODUCT MATCHES "^(development|control-sim|vision-node|robot-vision)$")
    message(FATAL_ERROR "Unknown RTCTRL_PRODUCT: ${RTCTRL_PRODUCT}")
endif()
set(RTCTRL_BUILD_CONTROL ON)
set(RTCTRL_BUILD_VISION OFF)
if(RTCTRL_PRODUCT STREQUAL "vision-node")
    set(RTCTRL_BUILD_CONTROL OFF)
endif()
if(RTCTRL_PRODUCT MATCHES "^(vision-node|robot-vision)$")
    set(RTCTRL_BUILD_VISION ON)
endif()
if(RTCTRL_ENABLE_IGH_ETHERCAT AND NOT RTCTRL_BUILD_CONTROL)
    message(FATAL_ERROR "IgH requires a control product")
endif()
include(cmake/Adapters.cmake)
find_package(Threads REQUIRED)
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)
include(cmake/BuildOptions.cmake)
include(cmake/Formatting.cmake)

rtctrl_add_build_options()
rtctrl_add_format_targets()

add_library(rtctrl_contracts INTERFACE)
target_link_libraries(rtctrl_contracts INTERFACE rtctrl_options)

if(RTCTRL_BUILD_CONTROL)
    add_subdirectory(src/platform)
    add_subdirectory(src/ipc)
    add_subdirectory(src/protocol)
    add_subdirectory(src/hal)
    add_subdirectory(src/control)
    add_subdirectory(src/transport)
    add_subdirectory(src/safety)
    add_subdirectory(src/runtime)
    add_subdirectory(src/bridge)

    if(RTCTRL_ENABLE_IGH_ETHERCAT)
        add_subdirectory(src/ethercat)
    endif()

    add_library(rtctrl INTERFACE)
    # Compatibility umbrella for existing consumers. New products link individual targets.
    target_link_libraries(rtctrl INTERFACE rtctrl_runtime rtctrl_platform rtctrl_hal
        rtctrl_control rtctrl_transport rtctrl_ipc rtctrl_bridge)
endif()

if(RTCTRL_BUILD_VISION)
    add_subdirectory(src/vision)
endif()

add_subdirectory(apps)

if(RTCTRL_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()

include(cmake/Architecture.cmake)
include(cmake/Install.cmake)
