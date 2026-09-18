cmake_minimum_required(VERSION 3.16)
project(rtctrl_speech_npu_probes LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(MODEL_ZOO_ROOT "" CACHE PATH "Official RKNN Model Zoo checkout")
set(RKNN_SDK_ROOT "" CACHE PATH "SDK external/rknpu2/runtime/Linux/librknn_api directory")
if(NOT EXISTS "${RKNN_SDK_ROOT}/include/rknn_api.h" OR
   NOT EXISTS "${RKNN_SDK_ROOT}/aarch64/librknnrt.so")
    message(FATAL_ERROR "Set RKNN_SDK_ROOT to the board SDK Linux librknn_api directory")
endif()
add_executable(rknn_tensor_runner tensor_runner.cc)
target_include_directories(rknn_tensor_runner PRIVATE "${RKNN_SDK_ROOT}/include")
target_link_libraries(rknn_tensor_runner PRIVATE "${RKNN_SDK_ROOT}/aarch64/librknnrt.so" pthread m)
set_target_properties(rknn_tensor_runner PROPERTIES SKIP_BUILD_RPATH TRUE)

if(MODEL_ZOO_ROOT)
    set(Z "${MODEL_ZOO_ROOT}")
    if(NOT EXISTS "${Z}/examples/zipformer/cpp/rknpu2/zipformer.cc")
        message(FATAL_ERROR "MODEL_ZOO_ROOT must contain the official zipformer example")
    endif()
    add_executable(rknn_zipformer_demo zipformer_main.cc
        "${Z}/examples/zipformer/cpp/process.cc"
        "${Z}/examples/zipformer/cpp/rknpu2/zipformer.cc"
        "${Z}/utils/audio_utils.c")
    target_include_directories(rknn_zipformer_demo PRIVATE
        "${Z}/examples/zipformer/cpp" "${Z}/utils" "${RKNN_SDK_ROOT}/include"
        "${Z}/3rdparty/timer" "${Z}/3rdparty/libsndfile/include"
        "${Z}/3rdparty/kaldi_native_fbank/include")
    target_link_libraries(rknn_zipformer_demo PRIVATE
        "${RKNN_SDK_ROOT}/aarch64/librknnrt.so"
        "${Z}/3rdparty/libsndfile/Linux/aarch64/libsndfile.a"
        "${Z}/3rdparty/kaldi_native_fbank/Linux/aarch64/libkaldi-native-fbank-core.a"
        pthread m)
    set_target_properties(rknn_zipformer_demo PROPERTIES SKIP_BUILD_RPATH TRUE)
endif()
# Deliberately no runtime-library installation: probes use the board's existing librknnrt.
