cmake_minimum_required(VERSION 3.16)
project(rtctrl_platform VERSION 0.5.0 LANGUAGES C CXX)

option(RTCTRL_ENABLE_SANITIZERS "Enable address and undefined-behavior sanitizers" OFF)
option(RTCTRL_ENABLE_TSAN "Enable thread sanitizer" OFF)
option(RTCTRL_BUILD_TESTS "Build unit tests" ON)
option(RTCTRL_ENABLE_IGH_ETHERCAT "Build the optional IgH EtherCAT ecrt adapter" OFF)
option(RTCTRL_ENABLE_FORMAT_TARGETS "Add clang-format check and rewrite targets" ON)
set(RTCTRL_IGH_ROOT "" CACHE PATH "IgH EtherCAT installation prefix")
set(RTCTRL_JOINT_COUNT 6 CACHE STRING "Compile-time logical joint count (1..64)")
if(RTCTRL_JOINT_COUNT LESS 1 OR RTCTRL_JOINT_COUNT GREATER 64)
    message(FATAL_ERROR "RTCTRL_JOINT_COUNT must be in [1, 64]")
endif()

find_package(Threads REQUIRED)
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

if(RTCTRL_ENABLE_FORMAT_TARGETS)
    find_program(RTCTRL_CLANG_FORMAT NAMES clang-format clang-format-19 clang-format-18
        clang-format-17 clang-format-16 clang-format-15 clang-format-14)
    if(RTCTRL_CLANG_FORMAT)
        file(GLOB_RECURSE RTCTRL_FORMAT_SOURCES CONFIGURE_DEPENDS
            "${CMAKE_CURRENT_SOURCE_DIR}/apps/*.cpp"
            "${CMAKE_CURRENT_SOURCE_DIR}/include/*.h"
            "${CMAKE_CURRENT_SOURCE_DIR}/include/*.hpp"
            "${CMAKE_CURRENT_SOURCE_DIR}/kernel/*.c"
            "${CMAKE_CURRENT_SOURCE_DIR}/kernel/*.h"
            "${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/*.c"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/*.cpp")
        add_custom_target(format
            COMMAND ${RTCTRL_CLANG_FORMAT} -i ${RTCTRL_FORMAT_SOURCES}
            COMMENT "Formatting C and C++ sources")
        add_custom_target(format-check
            COMMAND ${RTCTRL_CLANG_FORMAT} --dry-run --Werror ${RTCTRL_FORMAT_SOURCES}
            COMMENT "Checking C and C++ formatting")
    else()
        message(STATUS "clang-format not found; format targets are unavailable")
    endif()
endif()

add_library(rtctrl_options INTERFACE)
target_include_directories(rtctrl_options INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include/uapi>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/uapi>)
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

add_library(rtctrl_ipc
        src/ipc/posix_shared_memory.cpp
        src/ipc/kernel_mailbox_codec.cpp)
target_link_libraries(rtctrl_ipc PUBLIC rtctrl_options)

add_library(rtctrl_hal
        src/hal/dynamixel_protocol.cpp
        src/hal/simulated_hal.cpp
        src/hal/shared_memory_hal.cpp
        src/hal/kernel_mailbox_hal.cpp
        src/hal/half_duplex_serial_link.cpp
        src/hal/protocol_actuator_hal.cpp)
target_link_libraries(rtctrl_hal PUBLIC rtctrl_options rtctrl_ipc)

add_library(rtctrl_control
        src/control/joint_pd.cpp
        src/control/policy_action_mapper.cpp)
target_link_libraries(rtctrl_control PUBLIC rtctrl_options)

add_library(rtctrl_protocol
        src/protocol/fixed_target_codec.cpp
        src/protocol/dynamixel_v2.cpp)
target_link_libraries(rtctrl_protocol PUBLIC rtctrl_options)
target_link_libraries(rtctrl_hal PUBLIC rtctrl_protocol)

add_library(rtctrl_transport
        src/transport/loopback_source.cpp
        src/transport/loopback_byte_transport.cpp
        src/transport/framed_command_source.cpp
        src/transport/posix_serial_transport.cpp
        src/transport/socketcan_fd_transport.cpp)
target_link_libraries(rtctrl_transport PUBLIC rtctrl_options rtctrl_protocol)

if(RTCTRL_ENABLE_IGH_ETHERCAT)
    find_path(RTCTRL_IGH_INCLUDE_DIR ecrt.h
            HINTS ${RTCTRL_IGH_ROOT}
            PATH_SUFFIXES include)
    find_library(RTCTRL_IGH_LIBRARY ethercat
            HINTS ${RTCTRL_IGH_ROOT}
            PATH_SUFFIXES lib lib64)
    if(NOT RTCTRL_IGH_INCLUDE_DIR OR NOT RTCTRL_IGH_LIBRARY)
        message(FATAL_ERROR
                "IgH EtherCAT was requested but ecrt.h/libethercat were not found; set RTCTRL_IGH_ROOT")
    endif()
    if(NOT TARGET IgH::EtherCAT)
        add_library(IgH::EtherCAT UNKNOWN IMPORTED GLOBAL)
        set_target_properties(IgH::EtherCAT PROPERTIES
                IMPORTED_LOCATION "${RTCTRL_IGH_LIBRARY}"
                INTERFACE_INCLUDE_DIRECTORIES "${RTCTRL_IGH_INCLUDE_DIR}")
    endif()
    add_library(rtctrl_igh_ethercat src/ethercat/igh_master.cpp)
    target_link_libraries(rtctrl_igh_ethercat PUBLIC rtctrl_options IgH::EtherCAT)
endif()

add_library(rtctrl_safety src/safety/safety_policy.cpp)
target_link_libraries(rtctrl_safety PUBLIC rtctrl_options)

add_library(rtctrl_runtime src/runtime/realtime_engine.cpp)
target_link_libraries(rtctrl_runtime PUBLIC rtctrl_options rtctrl_platform rtctrl_hal
        rtctrl_control rtctrl_transport rtctrl_safety rtctrl_ipc Threads::Threads)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux" AND CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    # Some RV64 GCC targets lower even byte-sized std::atomic operations to
    # libatomic calls; make the installed runtime target carry that ABI need.
    target_link_libraries(rtctrl_runtime PUBLIC atomic)
endif()

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

    add_executable(rtctrl_uapi_c_test tests/uapi_c_compile.c)
    target_include_directories(rtctrl_uapi_c_test PRIVATE
            ${CMAKE_CURRENT_SOURCE_DIR}/include/uapi)
    target_compile_options(rtctrl_uapi_c_test PRIVATE
            -Wall -Wextra -Wpedantic -Wconversion)
    add_test(NAME rtctrl_uapi_c_test COMMAND rtctrl_uapi_c_test)

    add_executable(rtctrl_socketcan_vcan_test tests/test_socketcan_vcan.cpp)
    target_link_libraries(rtctrl_socketcan_vcan_test PRIVATE rtctrl_transport)
    add_test(NAME rtctrl_socketcan_vcan_test COMMAND rtctrl_socketcan_vcan_test)

    add_executable(rtctrl_dynamixel_test tests/test_dynamixel.cpp)
    target_link_libraries(rtctrl_dynamixel_test PRIVATE rtctrl_hal rtctrl_transport)
    add_test(NAME rtctrl_dynamixel_test COMMAND rtctrl_dynamixel_test)

    if(RTCTRL_ENABLE_IGH_ETHERCAT)
        add_executable(rtctrl_igh_contract_test tests/test_igh_contract.cpp)
        target_link_libraries(rtctrl_igh_contract_test PRIVATE rtctrl_igh_ethercat)
        add_test(NAME rtctrl_igh_contract_test COMMAND rtctrl_igh_contract_test)
    endif()
endif()

if(RTCTRL_ENABLE_IGH_ETHERCAT)
    install(TARGETS rtctrl_igh_ethercat
            EXPORT rtctrlTargets
            LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
            ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})
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
