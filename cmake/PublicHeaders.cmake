include("${CMAKE_CURRENT_LIST_DIR}/HeaderCheckHelpers.cmake")
# Replay the same checks using imported targets in a fresh installed consumer.
file(READ "${CMAKE_CURRENT_LIST_DIR}/HeaderCheckHelpers.cmake" helpers)
set(manifest "${PROJECT_BINARY_DIR}/public-header-checks.cmake")
file(WRITE "${manifest}" "${helpers}\n")
get_property(header_sets GLOBAL PROPERTY RTCTRL_MODULE_HEADERS)
set(seen_headers "")
set(header_count 0)
foreach(header_set IN LISTS header_sets)
    string(REPLACE "|" ";" fields "${header_set}")
    list(GET fields 0 owner)
    list(GET fields 1 directory)
    file(GLOB_RECURSE headers CONFIGURE_DEPENDS RELATIVE "${directory}"
        "${directory}/*.h" "${directory}/*.hpp")
    foreach(header IN LISTS headers)
        if(header IN_LIST seen_headers)
            message(FATAL_ERROR "Duplicate public header: ${header}")
        endif()
        list(APPEND seen_headers "${header}")
        math(EXPR header_count "${header_count} + 1")
        set(languages cpp)
        if(header MATCHES "\\.h$")
            list(APPEND languages c)
        endif()
        foreach(language IN LISTS languages)
            rtctrl_header_check("${owner}" "${header}" "${language}")
            file(APPEND "${manifest}"
                "rtctrl_header_check(rtctrl::${owner} \"${header}\" ${language})\n")
        endforeach()
    endforeach()
endforeach()
if(RTCTRL_BUILD_CONTROL)
    foreach(check
            "rtctrl_runtime_api|rtctrl/runtime/runtime_ports.hpp|1"
            "rtctrl_runtime_api|rtctrl/runtime/realtime_platform.hpp|1"
            "rtctrl_runtime_api|rtctrl/runtime/realtime_engine.hpp|0"
            "rtctrl_runtime_api|rtctrl/runtime/periodic_timer.hpp|0"
            "rtctrl_runtime_api|rtctrl/adapters/posix/posix_realtime.hpp|0"
            "rtctrl_timer|rtctrl/runtime/periodic_timer.hpp|1"
            "rtctrl_timer|rtctrl/runtime/realtime_engine.hpp|0"
            "rtctrl_bridge_api|rtctrl/runtime/realtime_engine.hpp|0"
            "rtctrl_transport_api|rtctrl/bridge/framed_command_source.hpp|0"
            "rtctrl_actuator_api|rtctrl/products/yidong23/topology.hpp|0"
            "rtctrl_actuator_api|rtctrl/profiles/yidong23_topology.hpp|0")
        string(REPLACE "|" ";" fields "${check}")
        list(GET fields 0 owner)
        list(GET fields 1 header)
        list(GET fields 2 expected)
        rtctrl_visibility_check("${owner}" "${header}" "${expected}")
        file(APPEND "${manifest}"
            "rtctrl_visibility_check(rtctrl::${owner} \"${header}\" ${expected})\n")
    endforeach()
endif()
message(STATUS "Checking ${header_count} public module headers through their owning targets")
