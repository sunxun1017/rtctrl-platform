get_property(RTCTRL_INSTALL_TARGETS GLOBAL PROPERTY RTCTRL_MODULE_TARGETS)
if(RTCTRL_BUILD_CONTROL)
    list(APPEND RTCTRL_INSTALL_TARGETS rtctrl_options)
endif()
install(TARGETS ${RTCTRL_INSTALL_TARGETS} EXPORT rtctrlTargets
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})
get_property(header_sets GLOBAL PROPERTY RTCTRL_MODULE_HEADERS)
foreach(header_set IN LISTS header_sets)
    string(REPLACE "|" ";" fields "${header_set}")
    list(GET fields 1 directory)
    list(GET fields 2 destination)
    install(DIRECTORY "${directory}/"
        DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}/rtctrl-modules/${destination}")
endforeach()
if(RTCTRL_BUILD_CONTROL AND RTCTRL_ENABLE_KERNEL_MAILBOX)
    install(DIRECTORY "${PROJECT_SOURCE_DIR}/include/uapi/" DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}/uapi")
endif()
foreach(app rtctrl_demo rtctrl_bench rtctrl_frame_demo rtctrl_vision_control_replay
        rtctrl_camera_capture rtctrl_camera_synthetic)
    if(TARGET ${app})
        install(TARGETS ${app} RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
    endif()
endforeach()
install(EXPORT rtctrlTargets FILE rtctrlTargets.cmake NAMESPACE rtctrl::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/rtctrl)
configure_package_config_file("${CMAKE_CURRENT_LIST_DIR}/rtctrlConfig.cmake.in"
    "${PROJECT_BINARY_DIR}/rtctrlConfig.cmake"
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/rtctrl)
write_basic_package_version_file("${PROJECT_BINARY_DIR}/rtctrlConfigVersion.cmake"
    VERSION ${PROJECT_VERSION} COMPATIBILITY SameMinorVersion)
install(FILES "${PROJECT_BINARY_DIR}/rtctrlConfig.cmake"
    "${PROJECT_BINARY_DIR}/rtctrlConfigVersion.cmake"
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/rtctrl)
