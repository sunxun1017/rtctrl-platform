if(RTCTRL_BUILD_CONTROL)
    add_executable(rtctrl_tests test_main.cpp)
    target_link_libraries(rtctrl_tests PRIVATE rtctrl)
    target_compile_definitions(rtctrl_tests PRIVATE
        RTCTRL_TEST_HAS_POSIX_SHM=$<BOOL:${RTCTRL_ENABLE_POSIX_SHM}>
        RTCTRL_TEST_HAS_MAILBOX=$<BOOL:${RTCTRL_ENABLE_KERNEL_MAILBOX}>
        RTCTRL_TEST_HAS_SOCKETCAN=$<BOOL:${RTCTRL_ENABLE_SOCKETCAN}>)
    add_test(NAME rtctrl_tests COMMAND rtctrl_tests)

    if(RTCTRL_ENABLE_KERNEL_MAILBOX)
        add_executable(rtctrl_uapi_c_test uapi_c_compile.c)
        target_include_directories(rtctrl_uapi_c_test PRIVATE ${PROJECT_SOURCE_DIR}/include/uapi)
        target_compile_options(rtctrl_uapi_c_test PRIVATE -Wall -Wextra -Wpedantic -Wconversion)
        add_test(NAME rtctrl_uapi_c_test COMMAND rtctrl_uapi_c_test)
    endif()

    if(RTCTRL_ENABLE_SOCKETCAN)
        add_executable(rtctrl_socketcan_vcan_test test_socketcan_vcan.cpp)
        target_link_libraries(rtctrl_socketcan_vcan_test PRIVATE rtctrl_transport)
        add_test(NAME rtctrl_socketcan_vcan_test COMMAND rtctrl_socketcan_vcan_test)
    endif()

    add_executable(rtctrl_dynamixel_test test_dynamixel.cpp)
    target_link_libraries(rtctrl_dynamixel_test PRIVATE rtctrl_hal rtctrl_transport)
    target_compile_definitions(rtctrl_dynamixel_test PRIVATE
        RTCTRL_TEST_HAS_SERIAL=$<BOOL:${RTCTRL_ENABLE_SERIAL}>)
    add_test(NAME rtctrl_dynamixel_test COMMAND rtctrl_dynamixel_test)

    if(RTCTRL_ENABLE_IGH_ETHERCAT)
        add_executable(rtctrl_igh_contract_test test_igh_contract.cpp)
        target_link_libraries(rtctrl_igh_contract_test PRIVATE rtctrl_igh_ethercat)
        add_test(NAME rtctrl_igh_contract_test COMMAND rtctrl_igh_contract_test)
    endif()

endif()

if(RTCTRL_BUILD_CONTROL)
    add_executable(rtctrl_architecture_test test_architecture.cpp)
    target_link_libraries(rtctrl_architecture_test PRIVATE rtctrl_runtime rtctrl_bridge
        rtctrl_control rtctrl_platform_posix)
    add_test(NAME rtctrl_architecture_test COMMAND rtctrl_architecture_test)
endif()
if(TARGET rtctrl_vision_v4l2 AND CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    add_executable(rtctrl_camera_test test_camera.c)
    target_link_libraries(rtctrl_camera_test PRIVATE rtctrl_vision_v4l2)
    target_link_options(rtctrl_camera_test PRIVATE
        -Wl,--wrap=open -Wl,--wrap=close -Wl,--wrap=mmap -Wl,--wrap=munmap
        -Wl,--wrap=poll -Wl,--wrap=ioctl)
    add_test(NAME rtctrl_camera_test COMMAND rtctrl_camera_test)
endif()

find_package(Python3 COMPONENTS Interpreter QUIET)
find_program(RTCTRL_PATCH_EXECUTABLE patch)
if(Python3_Interpreter_FOUND AND RTCTRL_PATCH_EXECUTABLE)
    add_test(NAME rtctrl_vendor_snapshot_test
        COMMAND ${Python3_EXECUTABLE} -B ${CMAKE_CURRENT_SOURCE_DIR}/test_vendor_snapshot.py)
endif()
if(TARGET rtctrl_vision_control_replay)
    add_test(NAME rtctrl_vision_control_replay_test COMMAND rtctrl_vision_control_replay
        ${CMAKE_CURRENT_SOURCE_DIR}/fixtures/vision-events.txt --arm)
    set_tests_properties(rtctrl_vision_control_replay_test PROPERTIES
        PASS_REGULAR_EXPRESSION "vision_disarmed=true fault_latched=false" TIMEOUT 5)
endif()
if(Python3_Interpreter_FOUND)
    add_test(NAME rtctrl_include_boundaries
        COMMAND ${Python3_EXECUTABLE} -B ${PROJECT_SOURCE_DIR}/scripts/check-architecture.py)
endif()
if(NOT CMAKE_CROSSCOMPILING)
    add_test(NAME rtctrl_package_consumer
        COMMAND ${CMAKE_COMMAND} -DRTCTRL_BUILD_DIR=${PROJECT_BINARY_DIR}
        -DRTCTRL_SOURCE_DIR=${PROJECT_SOURCE_DIR}
        -DCONTROL=${RTCTRL_BUILD_CONTROL} -DVISION=${RTCTRL_BUILD_VISION}
        -P ${PROJECT_SOURCE_DIR}/cmake/VerifyPackage.cmake)
endif()

if(RTCTRL_BUILD_VISION)
    add_executable(rtctrl_capture_backend_test test_capture_backend.c)
    target_link_libraries(rtctrl_capture_backend_test PRIVATE rtctrl_capture_synthetic)
    add_test(NAME rtctrl_capture_backend_test COMMAND rtctrl_capture_backend_test)
    add_test(NAME rtctrl_synthetic_cli_test COMMAND rtctrl_camera_synthetic)
    set_tests_properties(rtctrl_synthetic_cli_test PROPERTIES
        PASS_REGULAR_EXPRESSION "frames=70 corrupt=0 dropped=0 status=ok")
endif()
if(TARGET rtctrl_vision_v4l2)
    add_executable(rtctrl_v4l2_format_test test_v4l2_format.c)
    target_include_directories(rtctrl_v4l2_format_test PRIVATE ${PROJECT_SOURCE_DIR}/src/vision)
    target_link_libraries(rtctrl_v4l2_format_test PRIVATE rtctrl_vision_v4l2)
    add_test(NAME rtctrl_v4l2_format_test COMMAND rtctrl_v4l2_format_test)
endif()
if(RTCTRL_BUILD_VISION AND Python3_Interpreter_FOUND)
    add_test(NAME rtctrl_capture_cli_output_test COMMAND ${Python3_EXECUTABLE} -B
        ${CMAKE_CURRENT_SOURCE_DIR}/test_capture_cli.py $<TARGET_FILE:rtctrl_camera_synthetic>)
endif()
