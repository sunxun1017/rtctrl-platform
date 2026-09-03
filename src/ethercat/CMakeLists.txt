find_path(RTCTRL_IGH_INCLUDE_DIR ecrt.h HINTS ${RTCTRL_IGH_ROOT} PATH_SUFFIXES include)
find_library(RTCTRL_IGH_LIBRARY ethercat HINTS ${RTCTRL_IGH_ROOT} PATH_SUFFIXES lib lib64)
if(NOT RTCTRL_IGH_INCLUDE_DIR OR NOT RTCTRL_IGH_LIBRARY)
    message(FATAL_ERROR
        "IgH EtherCAT was requested but ecrt.h/libethercat were not found; set RTCTRL_IGH_ROOT")
endif()
if(NOT TARGET IgH::EtherCAT)
    add_library(IgH::EtherCAT UNKNOWN IMPORTED GLOBAL)
    set_target_properties(IgH::EtherCAT PROPERTIES
        IMPORTED_LOCATION "${RTCTRL_IGH_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${RTCTRL_IGH_INCLUDE_DIR}")
endif()
add_library(rtctrl_igh_ethercat igh_master.cpp)
target_link_libraries(rtctrl_igh_ethercat PUBLIC rtctrl_options IgH::EtherCAT)
