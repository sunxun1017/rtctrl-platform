set(RTCTRL_INSTALL_TARGETS
    rtctrl_options rtctrl_platform rtctrl_hal rtctrl_ipc rtctrl_control rtctrl_protocol
    rtctrl_transport rtctrl_safety rtctrl_runtime rtctrl rtctrl_demo rtctrl_bench
    rtctrl_frame_demo)

if(RTCTRL_ENABLE_IGH_ETHERCAT)
    list(APPEND RTCTRL_INSTALL_TARGETS rtctrl_igh_ethercat)
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
    COMPATIBILITY SameMajorVersion)
install(FILES
    "${PROJECT_BINARY_DIR}/rtctrlConfig.cmake"
    "${PROJECT_BINARY_DIR}/rtctrlConfigVersion.cmake"
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/rtctrl)
