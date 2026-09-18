#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Single-owner, serialized API. Exactly 256 mono int16 samples per buffer at 16kHz.
 * create enables CPU AEC + soft-reference delay estimation; enable_aes is 0 or 1.
 * process/reset/destroy return 0 on success, -1 on failure. destroy(NULL) is valid.
 * error text is thread-local and valid until the next operation on that thread.
 */
void* rtctrl_aec_create(int enable_aes);
int rtctrl_aec_process256(void* context,
                          const int16_t* mic,
                          const int16_t* reference,
                          int16_t* output);
int rtctrl_aec_reset(void* context);
int rtctrl_aec_destroy(void* context);
const char* rtctrl_aec_error(void);
#ifdef __cplusplus
}
#endif
