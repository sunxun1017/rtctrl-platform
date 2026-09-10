# Existing timer regression now proves it needs only its own module library.
add_executable(rtctrl_periodic_timer_test test_periodic_timer.cpp)
target_link_libraries(rtctrl_periodic_timer_test PRIVATE rtctrl_timer)
add_test(NAME rtctrl_periodic_timer_test COMMAND rtctrl_periodic_timer_test)
