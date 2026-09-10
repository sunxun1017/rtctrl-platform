#include "v4l2_format.h"
#include <stdio.h>
#include <string.h>
static int failures;
static void expect(int condition, const char* message) {
    if (!condition) {
        ++failures;
        fprintf(stderr, "%s\n", message);
    }
}
int main(void) {
    struct v4l2_pix_format_mplane native;
    memset(&native, 0, sizeof(native));
    native.width = 640;
    native.height = 480;
    native.num_planes = 1;
    native.pixelformat = V4L2_PIX_FMT_NV12;
    native.colorspace = V4L2_COLORSPACE_REC709;
    struct rtctrl_camera_format format;
    rtctrl_v4l2_translate_format(&native, &format);
    expect(format.pixel_format == RTCTRL_PIXEL_NV12 &&
               format.colorspace == RTCTRL_COLOR_REC709 &&
               format.quantization == RTCTRL_RANGE_LIMITED &&
               format.transfer_function == RTCTRL_TRANSFER_REC709 &&
               format.ycbcr_encoding == RTCTRL_YCBCR_BT709,
           "resolve YUV defaults into platform enums");
    native.colorspace = V4L2_COLORSPACE_JPEG;
    rtctrl_v4l2_translate_format(&native, &format);
    expect(format.colorspace == RTCTRL_COLOR_SRGB &&
               format.quantization == RTCTRL_RANGE_FULL &&
               format.transfer_function == RTCTRL_TRANSFER_SRGB &&
               format.ycbcr_encoding == RTCTRL_YCBCR_BT601,
           "JPEG shorthand is decomposed, not exposed as vendor number");
    native.pixelformat = V4L2_PIX_FMT_RGB24;
    native.colorspace = V4L2_COLORSPACE_SRGB;
    rtctrl_v4l2_translate_format(&native, &format);
    expect(format.pixel_format == RTCTRL_PIXEL_RGB24 &&
               format.quantization == RTCTRL_RANGE_FULL &&
               format.ycbcr_encoding == RTCTRL_YCBCR_UNKNOWN,
           "RGB has no YCbCr matrix");
    native.pixelformat = V4L2_PIX_FMT_NV12M;
    native.num_planes = 2;
    native.colorspace = V4L2_COLORSPACE_BT2020;
    native.quantization = V4L2_QUANTIZATION_LIM_RANGE;
    native.xfer_func = V4L2_XFER_FUNC_SMPTE2084;
    native.ycbcr_enc = V4L2_YCBCR_ENC_BT2020_CONST_LUM;
    rtctrl_v4l2_translate_format(&native, &format);
    expect(format.pixel_format == RTCTRL_PIXEL_NV12 && format.plane_count == 2 &&
               format.colorspace == RTCTRL_COLOR_BT2020 &&
               format.transfer_function == RTCTRL_TRANSFER_SMPTE2084 &&
               format.ycbcr_encoding == RTCTRL_YCBCR_BT2020_CONSTANT,
           "preserve explicit HDR metadata");
    native.colorspace = V4L2_COLORSPACE_DEFAULT;
    native.quantization = V4L2_QUANTIZATION_DEFAULT;
    native.xfer_func = V4L2_XFER_FUNC_DEFAULT;
    native.ycbcr_enc = V4L2_YCBCR_ENC_DEFAULT;
    rtctrl_v4l2_translate_format(&native, &format);
    expect(format.colorspace == RTCTRL_COLOR_UNKNOWN &&
               format.quantization == RTCTRL_RANGE_UNKNOWN &&
               format.transfer_function == RTCTRL_TRANSFER_UNKNOWN &&
               format.ycbcr_encoding == RTCTRL_YCBCR_UNKNOWN,
           "underspecified defaults must not be guessed from resolution");
    native.pixelformat = 0x12345678;
    native.colorspace = 999;
    native.quantization = native.xfer_func = native.ycbcr_enc = 255;
    rtctrl_v4l2_translate_format(&native, &format);
    expect(format.pixel_format == RTCTRL_PIXEL_UNKNOWN &&
               format.native_format == 0x12345678 &&
               format.colorspace == RTCTRL_COLOR_UNKNOWN &&
               format.quantization == RTCTRL_RANGE_UNKNOWN &&
               format.transfer_function == RTCTRL_TRANSFER_UNKNOWN &&
               format.ycbcr_encoding == RTCTRL_YCBCR_UNKNOWN,
           "unknown vendor values remain unknown with diagnostic format preserved");
    return failures ? 1 : 0;
}
