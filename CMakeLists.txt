cmake_minimum_required(VERSION 3.16)
project(rtctrl_platform VERSION 0.4.0 LANGUAGES CXX)

option(RTCTRL_ENABLE_SANITIZERS "Enable address and undefined-behavior sanitizers" OFF)
option(RTCTRL_ENABLE_TSAN "Enable thread sanitizer" OFF)
option(RTCTRL_BUILD_TESTS "Build unit tests" ON)
set(RTCTRL_JOINT_COUNT 6 CACHE STRING "Compile-time logical joint count (1..64)")
if(RTCTRL_JOINT_COUNT LESS 1 OR RTCTRL_JOINT_COUNT GREATER 64)
  message(FATAL_ERROR "RTCTRL_JOINT_COUNT must be in [1, 64]")
endif()

find_package(Threads REQUIRED)
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

add_library(rtctrl_options INTERFACE)
target_include_directories(rtctrl_options INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>)
target_compile_features(rtctrl_options INTERFACE cxx_std_17)
target_compile_definitions(rtctrl_options INTERFACE
    RTCTRL_JOINT_COUNT=${RTCTRL_JOINT_COUNT})
target_compile_options(rtctrl_options INTERFACE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)

if(RTCTRL_ENABLE_SANITIZERS AND RTCTRL_ENABLE_TSAN)
  message(FATAL_ERROR "ASan/UBSan and TSan must use separate builds")
endif()
if(RTCTRL_ENABLE_SANITIZERS AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(rtctrl_options INTERFACE -fsanitize=address,undefined -fno-omit-frame-pointer)
  target_link_options(rtctrl_options INTERFACE -fsanitize=address,undefined)
endif()
if(RTCTRL_ENABLE_TSAN AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(rtctrl_options INTERFACE -fsanitize=thread -fno-omit-frame-pointer)
  target_link_options(rtctrl_options INTERFACE -fsanitize=thread)
endif()

add_library(rtctrl_platform
    src/platform/realtime_platform.cpp
    src/platform/posix_realtime.cpp)
target_link_libraries(rtctrl_platform PUBLIC rtctrl_options Threads::Threads)

add_library(rtctrl_hal
    src/hal/simulated_hal.cpp
    src/hal/shared_memory_hal.cpp)
target_link_libraries(rtctrl_hal PUBLIC rtctrl_options)

add_library(rtctrl_ipc src/ipc/posix_shared_memory.cpp)
target_link_libraries(rtctrl_ipc PUBLIC rtctrl_options)

add_library(rtctrl_control
    src/control/joint_pd.cpp
    src/control/policy_action_mapper.cpp)
target_link_libraries(rtctrl_control PUBLIC rtctrl_options)

add_library(rtctrl_protocol src/protocol/fixed_target_codec.cpp)
target_link_libraries(rtctrl_protocol PUBLIC rtctrl_options)

add_library(rtctrl_transport
    src/transport/loopback_source.cpp
    src/transport/loopback_byte_transport.cpp
    src/transport/framed_command_source.cpp
    src/transport/posix_serial_transport.cpp)
target_link_libraries(rtctrl_transport PUBLIC rtctrl_options rtctrl_protocol)

add_library(rtctrl_safety src/safety/safety_policy.cpp)
target_link_libraries(rtctrl_safety PUBLIC rtctrl_options)

add_library(rtctrl_runtime src/runtime/realtime_engine.cpp)
target_link_libraries(rtctrl_runtime PUBLIC rtctrl_options rtctrl_platform rtctrl_hal
    rtctrl_control rtctrl_transport rtctrl_safety rtctrl_ipc Threads::Threads)

add_library(rtctrl INTERFACE)
target_link_libraries(rtctrl INTERFACE rtctrl_runtime)

add_executable(rtctrl_demo apps/rtctrl_demo.cpp)
target_link_libraries(rtctrl_demo PRIVATE rtctrl)

add_executable(rtctrl_bench apps/rtctrl_bench.cpp)
target_link_libraries(rtctrl_bench PRIVATE rtctrl)

add_executable(rtctrl_frame_demo apps/rtctrl_frame_demo.cpp)
target_link_libraries(rtctrl_frame_demo PRIVATE rtctrl_transport)

if(RTCTRL_BUILD_TESTS)
  enable_testing()
  add_executable(rtctrl_tests tests/test_main.cpp)
  target_link_libraries(rtctrl_tests PRIVATE rtctrl)
  add_test(NAME rtctrl_tests COMMAND rtctrl_tests)
endif()

install(TARGETS rtctrl_options rtctrl_platform rtctrl_hal rtctrl_ipc rtctrl_control rtctrl_protocol
    rtctrl_transport rtctrl_safety rtctrl_runtime rtctrl rtctrl_demo rtctrl_bench
    rtctrl_frame_demo
    EXPORT rtctrlTargets
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(EXPORT rtctrlTargets
    FILE rtctrlTargets.cmake
    NAMESPACE rtctrl::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/rtctrl)
configure_package_config_file(cmake/rtctrlConfig.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/rtctrlConfig.cmake
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/rtctrl)
write_basic_package_version_file(
    ${CMAKE_CURRENT_BINARY_DIR}/rtctrlConfigVersion.cmake
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion)
install(FILES
    ${CMAKE_CURRENT_BINARY_DIR}/rtctrlConfig.cmake
    ${CMAKE_CURRENT_BINARY_DIR}/rtctrlConfigVersion.cmake
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/rtctrl)
