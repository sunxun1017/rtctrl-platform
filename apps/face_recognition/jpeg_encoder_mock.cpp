#include <new>
#include <turbojpeg.h>
struct Context {
    int calls = 0;
};
extern "C" {
tjhandle tjInitCompress(void) {
    return new (std::nothrow) Context;
}
int tjDestroy(tjhandle h) {
    delete static_cast<Context*>(h);
    return 0;
}
unsigned long tjBufSize(int width, int height, int sampling) {
    return width > 0 && height > 0 && sampling == TJSAMP_420
               ? 64
               : static_cast<unsigned long>(-1);
}
char* tjGetErrorStr2(tjhandle) {
    static char text[] = "mock compression failure";
    return text;
}
int tjCompress2(tjhandle handle,
                const unsigned char* src,
                int w,
                int pitch,
                int h,
                int format,
                unsigned char** out,
                unsigned long* size,
                int sampling,
                int quality,
                int flags) {
    if (!handle || !src || !out || !*out || *size < 6 || pitch < w * 3 || h < 1 ||
        w < 1 || format != TJPF_BGR || sampling != TJSAMP_420 ||
        flags != (TJFLAG_ACCURATEDCT | TJFLAG_NOREALLOC) || quality == 13)
        return -1;
    if (quality == 14) {
        *size = 0;
        return 0;
    }
    ++static_cast<Context*>(handle)->calls;
    // Read the last row: catches incorrect handling of non-contiguous ROIs.
    const auto* last = src + (h - 1) * pitch;
    (*out)[0] = last[0];
    (*out)[1] = last[1];
    (*out)[2] = last[2];
    (*out)[3] = w;
    (*out)[4] = h;
    (*out)[5] = quality;
    *size = 6;
    return 0;
}
}
