function(rtctrl_add_format_targets)
    if(NOT RTCTRL_ENABLE_FORMAT_TARGETS)
        return()
    endif()

    find_program(RTCTRL_CLANG_FORMAT NAMES clang-format clang-format-19 clang-format-18
        clang-format-17 clang-format-16 clang-format-15 clang-format-14)
    if(NOT RTCTRL_CLANG_FORMAT)
        message(STATUS "clang-format not found; format targets are unavailable")
        return()
    endif()

    file(GLOB_RECURSE RTCTRL_FORMAT_SOURCES CONFIGURE_DEPENDS
        "${PROJECT_SOURCE_DIR}/apps/*.cpp"
        "${PROJECT_SOURCE_DIR}/include/*.h"
        "${PROJECT_SOURCE_DIR}/include/*.hpp"
        "${PROJECT_SOURCE_DIR}/kernel/*.c"
        "${PROJECT_SOURCE_DIR}/kernel/*.h"
        "${PROJECT_SOURCE_DIR}/src/*.cpp"
        "${PROJECT_SOURCE_DIR}/tests/*.c"
        "${PROJECT_SOURCE_DIR}/tests/*.cpp")
    add_custom_target(format
        COMMAND ${RTCTRL_CLANG_FORMAT} -i ${RTCTRL_FORMAT_SOURCES}
        COMMENT "Formatting C and C++ sources")
    add_custom_target(format-check
        COMMAND ${RTCTRL_CLANG_FORMAT} --dry-run --Werror ${RTCTRL_FORMAT_SOURCES}
        COMMENT "Checking C and C++ formatting")
endfunction()
