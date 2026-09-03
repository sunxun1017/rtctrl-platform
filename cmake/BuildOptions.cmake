function(rtctrl_add_build_options)
    if(RTCTRL_JOINT_COUNT LESS 1 OR RTCTRL_JOINT_COUNT GREATER 64)
        message(FATAL_ERROR "RTCTRL_JOINT_COUNT must be in [1, 64]")
    endif()
    if(RTCTRL_ENABLE_SANITIZERS AND RTCTRL_ENABLE_TSAN)
        message(FATAL_ERROR "ASan/UBSan and TSan must use separate builds")
    endif()

    add_library(rtctrl_options INTERFACE)
    target_include_directories(rtctrl_options INTERFACE
        $<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/include>
        $<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/include/uapi>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/uapi>)
    target_compile_features(rtctrl_options INTERFACE cxx_std_17)
    target_compile_definitions(rtctrl_options INTERFACE
        RTCTRL_JOINT_COUNT=${RTCTRL_JOINT_COUNT})
    target_compile_options(rtctrl_options INTERFACE
        -Wall -Wextra -Wpedantic -Wconversion -Wshadow)

    if(RTCTRL_ENABLE_SANITIZERS AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(rtctrl_options INTERFACE
            -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(rtctrl_options INTERFACE -fsanitize=address,undefined)
    endif()
    if(RTCTRL_ENABLE_TSAN AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(rtctrl_options INTERFACE
            -fsanitize=thread -fno-omit-frame-pointer)
        target_link_options(rtctrl_options INTERFACE -fsanitize=thread)
    endif()
endfunction()
