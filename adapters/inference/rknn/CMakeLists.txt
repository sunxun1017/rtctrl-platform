rtctrl_adapter(rtctrl_inference_rknn
    src/backend.cpp
    src/native_memory.cpp
)

target_compile_features(rtctrl_inference_rknn PUBLIC cxx_std_17)

target_include_directories(rtctrl_inference_rknn PUBLIC
    "${PROJECT_SOURCE_DIR}/third_party/rknn-toolkit/rknpu2/runtime/Linux/librknn_api/include"
)

target_link_libraries(rtctrl_inference_rknn PUBLIC rtctrl_inference)

if(RTCTRL_ENABLE_FACE_RECOGNITION AND RTCTRL_FACE_BUILD_CLI)
    if(NOT UNIX)
        message(FATAL_ERROR "RKNN runtime loader requires POSIX dlopen")
    endif()
    add_library(rtctrl_rknn_runtime_loader STATIC runtime_loader.cpp)
    target_compile_features(rtctrl_rknn_runtime_loader PRIVATE cxx_std_17)
    target_include_directories(rtctrl_rknn_runtime_loader PRIVATE
        "${PROJECT_SOURCE_DIR}/third_party/rknn-toolkit/rknpu2/runtime/Linux/librknn_api/include")
    target_link_libraries(rtctrl_rknn_runtime_loader PRIVATE ${CMAKE_DL_LIBS})
endif()
