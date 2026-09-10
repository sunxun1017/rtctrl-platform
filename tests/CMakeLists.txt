if(RTCTRL_BUILD_CONTROL)
    add_subdirectory(${PROJECT_SOURCE_DIR}/modules/runtime/tests ${CMAKE_CURRENT_BINARY_DIR}/runtime)
    add_subdirectory(${PROJECT_SOURCE_DIR}/products/yidong23/tests ${CMAKE_CURRENT_BINARY_DIR}/yidong23)
    add_executable(rtctrl_tests test_main.cpp)
    target_link_libraries(rtctrl_tests PRIVATE rtctrl_runtime rtctrl_bridge rtctrl_control
        rtctrl_hal_protocol rtctrl_hal_sim rtctrl_hal_shm rtctrl_actuator_serial_link
        rtctrl_actuator_dynamixel rtctrl_platform_posix rtctrl_source_loopback
        rtctrl_source_framed rtctrl_protocol_target rtctrl_protocol_dynamixel)
    foreach(adapter rtctrl_ipc_posix rtctrl_mailbox_codec rtctrl_transport_can)
        if(TARGET ${adapter})
            target_link_libraries(rtctrl_tests PRIVATE ${adapter})
        endif()
    endforeach()
    target_compile_definitions(rtctrl_tests PRIVATE
        RTCTRL_TEST_HAS_POSIX_SHM=$<BOOL:${RTCTRL_ENABLE_POSIX_SHM}>
        RTCTRL_TEST_HAS_MAILBOX=$<BOOL:${RTCTRL_ENABLE_KERNEL_MAILBOX}>
        RTCTRL_TEST_HAS_SOCKETCAN=$<BOOL:${RTCTRL_ENABLE_SOCKETCAN}>)
    add_test(NAME rtctrl_tests COMMAND rtctrl_tests)

    foreach(adapter actuator/mailbox transport/socketcan ethercat/igh)
        if(EXISTS "${PROJECT_SOURCE_DIR}/adapters/${adapter}/tests/CMakeLists.txt")
            add_subdirectory("${PROJECT_SOURCE_DIR}/adapters/${adapter}/tests" "${CMAKE_CURRENT_BINARY_DIR}/${adapter}")
        endif()
    endforeach()

    add_executable(rtctrl_dynamixel_test test_dynamixel.cpp)
    target_link_libraries(rtctrl_dynamixel_test PRIVATE rtctrl_actuator_dynamixel rtctrl_actuator_serial_link)
    if(TARGET rtctrl_transport_serial)
        target_link_libraries(rtctrl_dynamixel_test PRIVATE rtctrl_transport_serial)
    endif()
    target_compile_definitions(rtctrl_dynamixel_test PRIVATE
        RTCTRL_TEST_HAS_SERIAL=$<BOOL:${RTCTRL_ENABLE_SERIAL}>)
    add_test(NAME rtctrl_dynamixel_test COMMAND rtctrl_dynamixel_test)
endif()

if(RTCTRL_BUILD_CONTROL)
    add_executable(rtctrl_architecture_test test_architecture.cpp)
    target_link_libraries(rtctrl_architecture_test PRIVATE rtctrl_runtime rtctrl_bridge
        rtctrl_control rtctrl_platform_posix)
    add_test(NAME rtctrl_architecture_test COMMAND rtctrl_architecture_test)
endif()
if(TARGET rtctrl_vision_v4l2)
    add_subdirectory(${PROJECT_SOURCE_DIR}/adapters/capture/v4l2/tests ${CMAKE_CURRENT_BINARY_DIR}/v4l2)
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
    add_subdirectory(${PROJECT_SOURCE_DIR}/modules/capture/tests ${CMAKE_CURRENT_BINARY_DIR}/capture)
    add_test(NAME rtctrl_synthetic_cli_test COMMAND rtctrl_camera_synthetic)
    set_tests_properties(rtctrl_synthetic_cli_test PROPERTIES
        PASS_REGULAR_EXPRESSION "frames=70 corrupt=0 dropped=0 status=ok")
endif()
if(RTCTRL_BUILD_VISION AND Python3_Interpreter_FOUND)
    add_test(NAME rtctrl_capture_cli_output_test COMMAND ${Python3_EXECUTABLE} -B
        ${CMAKE_CURRENT_SOURCE_DIR}/test_capture_cli.py $<TARGET_FILE:rtctrl_camera_synthetic>)
endif()

# Test the RKNN bridge through the module interface without a hardware runtime.
if(NOT CMAKE_CROSSCOMPILING AND EXISTS
        "${PROJECT_SOURCE_DIR}/third_party/rknn-toolkit/rknpu2/runtime/Linux/librknn_api/include/rknn_api.h")
    add_subdirectory(${PROJECT_SOURCE_DIR}/adapters/inference/rknn/tests
        ${CMAKE_CURRENT_BINARY_DIR}/rknn)
endif()
