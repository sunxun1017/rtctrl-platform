set(RTCTRL_INSTALL_TARGETS rtctrl_options rtctrl_contracts)
if(RTCTRL_BUILD_CONTROL)
    list(APPEND RTCTRL_INSTALL_TARGETS rtctrl_timer rtctrl_platform_posix rtctrl_platform
        rtctrl_hal_sim rtctrl_hal_protocol rtctrl_hal_shm rtctrl_hal_mailbox rtctrl_hal
        rtctrl_ipc_posix rtctrl_mailbox_codec rtctrl_ipc rtctrl_control rtctrl_protocol
        rtctrl_source_loopback rtctrl_source_framed rtctrl_transport_serial rtctrl_transport_can
        rtctrl_transport rtctrl_safety rtctrl_runtime rtctrl_bridge rtctrl
        rtctrl_demo rtctrl_bench rtctrl_frame_demo)
endif()
if(RTCTRL_BUILD_VISION)
    list(APPEND RTCTRL_INSTALL_TARGETS rtctrl_vision_v4l2 rtctrl_camera_capture)
endif()
if(RTCTRL_ENABLE_IGH_ETHERCAT)
    list(APPEND RTCTRL_INSTALL_TARGETS rtctrl_igh_ethercat)
endif()

if(TARGET rtctrl_vision_control_replay)
    list(APPEND RTCTRL_INSTALL_TARGETS rtctrl_vision_control_replay)
endif()

install(TARGETS ${RTCTRL_INSTALL_TARGETS}
    EXPORT rtctrlTargets
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(DIRECTORY "${PROJECT_SOURCE_DIR}/include/" DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(EXPORT rtctrlTargets
    FILE rtctrlTargets.cmake
    NAMESPACE rtctrl::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/rtctrl)
configure_package_config_file(
    "${CMAKE_CURRENT_LIST_DIR}/rtctrlConfig.cmake.in"
    "${PROJECT_BINARY_DIR}/rtctrlConfig.cmake"
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/rtctrl)
write_basic_package_version_file(
    "${PROJECT_BINARY_DIR}/rtctrlConfigVersion.cmake"
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY SameMinorVersion)
install(FILES
    "${PROJECT_BINARY_DIR}/rtctrlConfig.cmake"
    "${PROJECT_BINARY_DIR}/rtctrlConfigVersion.cmake"
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/rtctrl)
