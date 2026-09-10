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
# Modules may depend only on module targets and explicit host runtime support.
get_property(module_targets GLOBAL PROPERTY RTCTRL_MODULE_TARGETS)
set(module_allowed ${module_targets} rtctrl_options Threads::Threads atomic)
foreach(target IN LISTS module_targets)
    rtctrl_check_closure(${target} "${module_allowed}" "")
endforeach()
if(RTCTRL_BUILD_CONTROL)
    rtctrl_check_closure(rtctrl_runtime_api
        "rtctrl_runtime_api;rtctrl_model_api;rtctrl_options" "")
    rtctrl_check_closure(rtctrl_transport_api
        "rtctrl_transport_api;rtctrl_options" "")
    rtctrl_check_closure(rtctrl_runtime
        "rtctrl_runtime;rtctrl_runtime_api;rtctrl_model_api;rtctrl_options;rtctrl_timer;rtctrl_safety;rtctrl_safety_api;rtctrl_control_api;rtctrl_actuator_api;rtctrl_transport_api;rtctrl_ipc_api;Threads::Threads;atomic" "")
    rtctrl_check_closure(rtctrl_bridge
        "rtctrl_bridge;rtctrl_bridge_api;rtctrl_runtime_api;rtctrl_vision_api;rtctrl_model_api;rtctrl_options;rtctrl_transport_api;rtctrl_protocol_api" "")
endif()
if(RTCTRL_BUILD_VISION)
    rtctrl_check_closure(rtctrl_capture "rtctrl_capture;rtctrl_capture_api" "")
    rtctrl_check_closure(rtctrl_capture_cli "rtctrl_capture_cli;rtctrl_capture;rtctrl_capture_api" "")
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
