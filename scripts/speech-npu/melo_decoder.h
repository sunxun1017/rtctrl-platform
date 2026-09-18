#ifndef RTCTRL_MELO_DECODER_H
#define RTCTRL_MELO_DECODER_H
#ifdef __cplusplus
extern "C" {
#endif
/* Opaque handles are single-owner and must be used serially. Model is loaded once.
 * Error text is thread-local, valid until the next API operation on that thread.
 * create returns NULL on failure; run/destroy return 0 on success, -1 on failure.
 * run requires latent[192*256] and output[131072] float32 buffers;
 * valid_length 1..256. Only successful run writes output. Caller trims output to
 * valid_length * 512. destroy(NULL) is valid. A destroyed handle must never be
 * reused.
 */
void* melo_decoder_create(const char* path);
int melo_decoder_run(void* context,
                     const float* latent,
                     unsigned valid_length,
                     float* output);
int melo_decoder_destroy(void* context);
const char* melo_decoder_error(void);
#ifdef __cplusplus
}
#endif
#endif
