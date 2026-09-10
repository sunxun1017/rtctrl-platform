# Product wiring/calibration is available only to explicit source-tree consumers.
add_library(rtctrl_product_yidong23 INTERFACE)
target_include_directories(rtctrl_product_yidong23 INTERFACE "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_link_libraries(rtctrl_product_yidong23 INTERFACE rtctrl_actuator_api)
