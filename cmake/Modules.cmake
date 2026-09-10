include_guard(GLOBAL)
# A header root belongs to exactly one target, both in-tree and after installation.
function(rtctrl_module_headers target directory destination)
    get_target_property(kind ${target} TYPE)
    if(kind STREQUAL "INTERFACE_LIBRARY")
        set(scope INTERFACE)
    else()
        set(scope PUBLIC)
    endif()
    set(header_root "${CMAKE_CURRENT_SOURCE_DIR}/${directory}")
    target_include_directories(${target} ${scope}
        $<BUILD_INTERFACE:${header_root}>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/rtctrl-modules/${destination}>)
    set_property(GLOBAL APPEND PROPERTY RTCTRL_MODULE_HEADERS
        "${target}|${header_root}|${destination}")
endfunction()

function(rtctrl_module_api name)
    add_library(rtctrl_${name}_api INTERFACE)
    set_property(GLOBAL APPEND PROPERTY RTCTRL_MODULE_TARGETS rtctrl_${name}_api)
    if(ARGC GREATER 1)
        rtctrl_module_headers(rtctrl_${name}_api "${ARGV1}" "${name}/ports")
    else()
        rtctrl_module_headers(rtctrl_${name}_api include "${name}")
    endif()
endfunction()

function(rtctrl_module_library target)
    add_library(${target} ${ARGN})
    set_property(GLOBAL APPEND PROPERTY RTCTRL_MODULE_TARGETS ${target})
endfunction()

function(rtctrl_adapter target)
    # Adapters are application dependencies, not installed public module APIs.
    add_library(${target} STATIC ${ARGN})
    set_target_properties(${target} PROPERTIES POSITION_INDEPENDENT_CODE ON)
    target_include_directories(${target} PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
    set_property(GLOBAL APPEND PROPERTY RTCTRL_ADAPTER_TARGETS ${target})
endfunction()
