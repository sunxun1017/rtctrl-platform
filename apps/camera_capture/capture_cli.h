#ifndef RTCTRL_CAPTURE_CLI_H
#define RTCTRL_CAPTURE_CLI_H
#include "rtctrl/vision/capture.h"
void rtctrl_capture_prepare_signals(void);
/* Takes ownership of camera, including all failure paths. */
int rtctrl_capture_run(struct rtctrl_camera* camera, const char* output_path);
#endif
