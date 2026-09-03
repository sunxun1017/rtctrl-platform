add_executable(rtctrl_tests test_main.cpp)
target_link_libraries(rtctrl_tests PRIVATE rtctrl)
add_test(NAME rtctrl_tests COMMAND rtctrl_tests)

add_executable(rtctrl_uapi_c_test uapi_c_compile.c)
target_include_directories(rtctrl_uapi_c_test PRIVATE ${PROJECT_SOURCE_DIR}/include/uapi)
target_compile_options(rtctrl_uapi_c_test PRIVATE -Wall -Wextra -Wpedantic -Wconversion)
add_test(NAME rtctrl_uapi_c_test COMMAND rtctrl_uapi_c_test)

add_executable(rtctrl_socketcan_vcan_test test_socketcan_vcan.cpp)
target_link_libraries(rtctrl_socketcan_vcan_test PRIVATE rtctrl_transport)
add_test(NAME rtctrl_socketcan_vcan_test COMMAND rtctrl_socketcan_vcan_test)

add_executable(rtctrl_dynamixel_test test_dynamixel.cpp)
target_link_libraries(rtctrl_dynamixel_test PRIVATE rtctrl_hal rtctrl_transport)
add_test(NAME rtctrl_dynamixel_test COMMAND rtctrl_dynamixel_test)

if(RTCTRL_ENABLE_IGH_ETHERCAT)
    add_executable(rtctrl_igh_contract_test test_igh_contract.cpp)
    target_link_libraries(rtctrl_igh_contract_test PRIVATE rtctrl_igh_ethercat)
    add_test(NAME rtctrl_igh_contract_test COMMAND rtctrl_igh_contract_test)
endif()
