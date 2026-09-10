if(NOT DEFINED RTCTRL_BUILD_DIR OR NOT DEFINED RTCTRL_SOURCE_DIR)
    message(FATAL_ERROR "Build/source directories are required")
endif()
set(check_dir "${RTCTRL_BUILD_DIR}/package-check")
# Check a fresh package; stale headers from previous layouts hide export mistakes.
file(REMOVE_RECURSE "${check_dir}/install" "${check_dir}/build")
execute_process(COMMAND "${CMAKE_COMMAND}" --install "${RTCTRL_BUILD_DIR}"
    --prefix "${check_dir}/install" RESULT_VARIABLE result OUTPUT_QUIET)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "Package installation failed")
endif()
file(GLOB_RECURSE installed_adapter_headers "${check_dir}/install/include/*/adapters/*.h"
    "${check_dir}/install/include/*/adapters/*.hpp")
file(GLOB_RECURSE installed_product_headers
    "${check_dir}/install/include/*/products/*.hpp"
    "${check_dir}/install/include/*/profiles/yidong23_topology.hpp")
if(installed_product_headers)
    message(FATAL_ERROR "Product headers leaked into the public module package")
endif()
if(installed_adapter_headers)
    message(FATAL_ERROR "Adapter headers leaked into the public module package")
endif()
file(MAKE_DIRECTORY "${check_dir}/consumer")
configure_file("${RTCTRL_BUILD_DIR}/public-header-checks.cmake"
    "${check_dir}/consumer/public-header-checks.cmake" COPYONLY)
file(WRITE "${check_dir}/consumer/CMakeLists.txt" [=[
cmake_minimum_required(VERSION 3.16)
project(rtctrl_external_consumer LANGUAGES C CXX)
find_package(rtctrl 0.8 REQUIRED CONFIG)
include("${CMAKE_CURRENT_SOURCE_DIR}/public-header-checks.cmake")
if(TARGET rtctrl::rtctrl_product_yidong23)
    message(FATAL_ERROR "Product profile leaked into the public module package")
endif()
foreach(adapter rtctrl_vision_v4l2 rtctrl_capture_synthetic rtctrl_platform_posix
        rtctrl_hal_sim rtctrl_hal_mailbox rtctrl_ipc_posix rtctrl_transport_serial
        rtctrl_transport_can rtctrl_igh_ethercat)
    if(TARGET rtctrl::${adapter})
        message(FATAL_ERROR "Adapter target leaked into the public module package: ${adapter}")
    endif()
endforeach()
if(CONTROL)
    add_executable(core core.cpp)
    target_link_libraries(core PRIVATE rtctrl::rtctrl_runtime)
    include(CheckCXXSourceCompiles)
    set(CMAKE_REQUIRED_LIBRARIES rtctrl::rtctrl_runtime)
    check_cxx_source_compiles("#include <rtctrl/runtime/realtime_platform.hpp>\nint main() { return 0; }" HAS_RUNTIME_PORT)
    check_cxx_source_compiles("#include <rtctrl/adapters/posix/posix_realtime.hpp>\nint main() { return 0; }" HAS_POSIX_ADAPTER)
    if(NOT HAS_RUNTIME_PORT OR HAS_POSIX_ADAPTER)
        message(FATAL_ERROR "Installed runtime port/adapter visibility is incorrect")
    endif()
    unset(CMAKE_REQUIRED_LIBRARIES)
elseif(TARGET rtctrl::rtctrl_runtime)
    message(FATAL_ERROR "Vision-only package unexpectedly exports control runtime")
endif()
if(VISION)
    add_executable(capture_core capture_core.c)
    target_link_libraries(capture_core PRIVATE rtctrl::rtctrl_capture)
    add_executable(camera camera.c)
    target_link_libraries(camera PRIVATE rtctrl::rtctrl_capture)
endif()
]=])
file(WRITE "${check_dir}/consumer/core.cpp" [=[
#include <rtctrl/runtime/realtime_engine.hpp>
bool inspect(rtctrl::runtime::RealtimeEngine& engine) { return engine.state() == rtctrl::runtime::RuntimeState::Armed; }
int main() { return 0; }
]=])
file(WRITE "${check_dir}/consumer/camera.c" [=[
#include <rtctrl/capture/capture_backend.h>
#include <errno.h>
static int open_backend(const void* config, void** context) { (void)config; *context = 0; return -ENODEV; }
static int format(const void* context, struct rtctrl_camera_format* output) { (void)context; (void)output; return -ENODEV; }
static int acquire(void* context, int timeout, struct rtctrl_camera_frame* output) { (void)context; (void)timeout; (void)output; return -ENODEV; }
static int release(void* context, uint64_t token) { (void)context; (void)token; return 0; }
static int close_backend(void* context) { (void)context; return 0; }
int main(void) {
    const struct rtctrl_capture_backend backend = {1, open_backend, format, acquire, release, close_backend};
    struct rtctrl_camera* camera = 0;
    return rtctrl_camera_create(&backend, 0, &camera) == -ENODEV && camera == 0 ? 0 : 1;
}
]=])
file(WRITE "${check_dir}/consumer/capture_core.c" [=[
#include <rtctrl/capture/capture.h>
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
if(CONTROL)
    execute_process(COMMAND "${check_dir}/build/core" RESULT_VARIABLE result)
    if(NOT result EQUAL 0)
        message(FATAL_ERROR "External runtime consumer failed")
    endif()
endif()
if(VISION)
    foreach(consumer capture_core camera)
        execute_process(COMMAND "${check_dir}/build/${consumer}" RESULT_VARIABLE result)
        if(NOT result EQUAL 0)
            message(FATAL_ERROR "External capture consumer failed: ${consumer}")
        endif()
    endforeach()
endif()
