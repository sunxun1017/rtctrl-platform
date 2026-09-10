cmake_minimum_required(VERSION 3.16)
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(rknn_backend_contract_tests LANGUAGES CXX)
    enable_testing()
endif()
get_filename_component(REPO_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../.." ABSOLUTE)
add_executable(rknn_backend_contract_test backend_test.cpp ../src/backend.cpp)
target_compile_features(rknn_backend_contract_test PRIVATE cxx_std_17)
target_include_directories(rknn_backend_contract_test PRIVATE
    ../include
    "${REPO_ROOT}/third_party/rknn-toolkit/rknpu2/runtime/Linux/librknn_api/include")
if(TARGET rtctrl_inference)
    target_link_libraries(rknn_backend_contract_test PRIVATE rtctrl_inference)
else()
    target_sources(rknn_backend_contract_test PRIVATE
        "${REPO_ROOT}/modules/inference/src/tensor.cpp")
    target_include_directories(rknn_backend_contract_test PRIVATE
        "${REPO_ROOT}/modules/inference/include")
endif()
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/fake.rknn" "host test fixture")
add_test(NAME rknn_backend_contract COMMAND rknn_backend_contract_test
    "${CMAKE_CURRENT_BINARY_DIR}/fake.rknn")

add_executable(rknn_native_memory_test native_memory_test.cpp ../src/native_memory.cpp)
target_compile_features(rknn_native_memory_test PRIVATE cxx_std_17)
target_include_directories(rknn_native_memory_test PRIVATE ../include
    "${REPO_ROOT}/third_party/rknn-toolkit/rknpu2/runtime/Linux/librknn_api/include")
add_test(NAME rknn_native_memory COMMAND rknn_native_memory_test)
