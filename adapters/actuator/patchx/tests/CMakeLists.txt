add_executable(rtctrl_patchx_codec_test test_patchx_codec.cpp)
target_link_libraries(rtctrl_patchx_codec_test PRIVATE rtctrl_patchx_codec rtctrl_source_loopback)
add_test(NAME rtctrl_patchx_codec_test COMMAND rtctrl_patchx_codec_test)

# The serial adapter is declared later by the composition root.
if(RTCTRL_ENABLE_SERIAL)
    add_executable(rtctrl_patchx_pty_test test_patchx_pty.cpp)
    target_link_libraries(rtctrl_patchx_pty_test PRIVATE rtctrl_patchx_codec rtctrl_transport_serial)
    add_test(NAME rtctrl_patchx_pty_test COMMAND rtctrl_patchx_pty_test)
    set_tests_properties(rtctrl_patchx_pty_test PROPERTIES TIMEOUT 10)
endif()
