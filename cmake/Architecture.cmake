# Check the complete target closure at configure time, including PUBLIC and
# PRIVATE links. Compatibility umbrellas are allowed only at composition roots.
function(rtctrl_check_closure target allowed visited)
    if("${target}" IN_LIST visited)
        return()
    endif()
    if(NOT "${target}" IN_LIST allowed)
        message(FATAL_ERROR "Architecture violation: forbidden dependency ${target}")
    endif()
    list(APPEND visited "${target}")
    if(NOT TARGET "${target}")
        return()
    endif()
    get_target_property(imported "${target}" IMPORTED)
    if(imported)
        return()
    endif()
    foreach(property LINK_LIBRARIES INTERFACE_LINK_LIBRARIES)
        get_target_property(dependencies "${target}" ${property})
        if(dependencies)
            foreach(dependency IN LISTS dependencies)
                # Static libraries expose private links this way.
                string(REGEX REPLACE "^\\$<LINK_ONLY:(.*)>$" "\\1" dependency "${dependency}")
                rtctrl_check_closure("${dependency}" "${allowed}" "${visited}")
            endforeach()
        endif()
    endforeach()
endfunction()
if(RTCTRL_BUILD_CONTROL)
    rtctrl_check_closure(rtctrl_runtime
        "rtctrl_runtime;rtctrl_contracts;rtctrl_options;rtctrl_timer;rtctrl_safety;Threads::Threads;atomic" "")
    rtctrl_check_closure(rtctrl_bridge "rtctrl_bridge;rtctrl_contracts;rtctrl_options" "")
    rtctrl_check_closure(rtctrl_control "rtctrl_control;rtctrl_contracts;rtctrl_options" "")
endif()
if(RTCTRL_BUILD_VISION)
    rtctrl_check_closure(rtctrl_capture "rtctrl_capture;rtctrl_capture_contracts" "")
    rtctrl_check_closure(rtctrl_capture_synthetic
        "rtctrl_capture_synthetic;rtctrl_capture;rtctrl_capture_contracts" "")
    if(TARGET rtctrl_vision_v4l2)
        rtctrl_check_closure(rtctrl_vision_v4l2
            "rtctrl_vision_v4l2;rtctrl_capture;rtctrl_capture_contracts" "")
    endif()
    rtctrl_check_closure(rtctrl_capture_cli
        "rtctrl_capture_cli;rtctrl_capture;rtctrl_capture_contracts" "")
endif()

if(RTCTRL_BUILD_CONTROL)
    rtctrl_check_closure(rtctrl_hal_protocol "rtctrl_hal_protocol;rtctrl_contracts;rtctrl_options" "")
    rtctrl_check_closure(rtctrl_actuator_serial_link "rtctrl_actuator_serial_link;rtctrl_contracts;rtctrl_options" "")
    rtctrl_check_closure(rtctrl_source_framed
        "rtctrl_source_framed;rtctrl_protocol_target;rtctrl_contracts;rtctrl_options" "")
endif()

# Disabled capabilities must remove targets, not merely remove a link from demo.
foreach(pair "POSIX_SHM|rtctrl_ipc_posix" "KERNEL_MAILBOX|rtctrl_hal_mailbox"
        "KERNEL_MAILBOX|rtctrl_mailbox_codec" "SERIAL|rtctrl_transport_serial"
        "SOCKETCAN|rtctrl_transport_can" "V4L2|rtctrl_vision_v4l2")
    string(REPLACE "|" ";" parts "${pair}")
    list(GET parts 0 capability)
    list(GET parts 1 adapter)
    if(NOT RTCTRL_ENABLE_${capability} AND TARGET ${adapter})
        message(FATAL_ERROR "Disabled adapter is still being built: ${adapter}")
    endif()
endforeach()
