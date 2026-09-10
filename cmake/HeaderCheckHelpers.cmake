# Each translation unit receives only the usage requirements of its owner.
function(rtctrl_header_check owner header language)
    string(MD5 id "${owner}|${header}|${language}")
    set(source "${CMAKE_CURRENT_BINARY_DIR}/header-checks/${id}.${language}")
    file(WRITE "${source}" "#include <${header}>\ntypedef int rtctrl_header_translation_unit;\n")
    add_library(rtctrl_header_${id} OBJECT "${source}")
    target_link_libraries(rtctrl_header_${id} PRIVATE ${owner})
endfunction()

function(rtctrl_visibility_check owner header expected)
    string(MD5 id "visibility|${owner}|${header}")
    set(source "${CMAKE_CURRENT_BINARY_DIR}/header-checks/${id}.cpp")
    file(WRITE "${source}"
        "#if __has_include(<${header}>) != ${expected}\n#error Unexpected header visibility\n#endif\n")
    add_library(rtctrl_visibility_${id} OBJECT "${source}")
    target_link_libraries(rtctrl_visibility_${id} PRIVATE ${owner})
    target_compile_features(rtctrl_visibility_${id} PRIVATE cxx_std_17)
endfunction()
