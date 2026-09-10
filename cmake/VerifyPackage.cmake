if(NOT DEFINED RTCTRL_BUILD_DIR OR NOT DEFINED RTCTRL_SOURCE_DIR)
    message(FATAL_ERROR "Build/source directories are required")
endif()
set(check_dir "${RTCTRL_BUILD_DIR}/package-check")
execute_process(COMMAND "${CMAKE_COMMAND}" --install "${RTCTRL_BUILD_DIR}"
    --prefix "${check_dir}/install" RESULT_VARIABLE result OUTPUT_QUIET)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "Package installation failed")
endif()
file(MAKE_DIRECTORY "${check_dir}/consumer")
file(WRITE "${check_dir}/consumer/CMakeLists.txt" [=[
cmake_minimum_required(VERSION 3.16)
project(rtctrl_external_consumer LANGUAGES C CXX)
find_package(rtctrl 0.7 REQUIRED CONFIG)
if(CONTROL)
    add_executable(core core.cpp)
    target_link_libraries(core PRIVATE rtctrl::rtctrl_runtime)
elseif(TARGET rtctrl::rtctrl_runtime)
    message(FATAL_ERROR "Vision-only package unexpectedly exports control runtime")
endif()
if(VISION)
    add_executable(capture_core capture_core.c)
    target_link_libraries(capture_core PRIVATE rtctrl::rtctrl_capture)
    add_executable(camera camera.c)
    target_link_libraries(camera PRIVATE rtctrl::rtctrl_capture_synthetic)
endif()
]=])
file(WRITE "${check_dir}/consumer/core.cpp" [=[
#include <rtctrl/runtime/realtime_engine.hpp>
bool inspect(rtctrl::runtime::RealtimeEngine& engine) { return engine.state() == rtctrl::bridge::RuntimeState::Armed; }
int main() { return 0; }
]=])
file(WRITE "${check_dir}/consumer/camera.c" [=[
#include <rtctrl/vision/synthetic_capture.h>
int main(void) {
    struct rtctrl_camera* camera = 0;
    struct rtctrl_synthetic_config config = {8, 8};
    if (rtctrl_synthetic_open(&config, &camera)) { return 1; }
    return rtctrl_camera_close(camera);
}
]=])
file(WRITE "${check_dir}/consumer/capture_core.c" [=[
#include <rtctrl/vision/capture.h>
int main(void) {
    struct rtctrl_camera* camera = 0;
    return rtctrl_camera_create(0, 0, &camera) < 0 ? 0 : 1;
}
]=])
execute_process(COMMAND "${CMAKE_COMMAND}" -S "${check_dir}/consumer" -B "${check_dir}/build"
    "-DCMAKE_PREFIX_PATH=${check_dir}/install" "-DCONTROL=${CONTROL}" "-DVISION=${VISION}"
    RESULT_VARIABLE result OUTPUT_QUIET)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "External consumer configuration failed")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" --build "${check_dir}/build"
    RESULT_VARIABLE result OUTPUT_QUIET)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "External consumer linking failed")
endif()
