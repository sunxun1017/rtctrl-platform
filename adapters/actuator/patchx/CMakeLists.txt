rtctrl_adapter(rtctrl_patchx_codec src/patchx_codec.cpp)
target_link_libraries(rtctrl_patchx_codec PUBLIC rtctrl_options)

if(RTCTRL_BUILD_TESTS)
    add_subdirectory(tests)
endif()
