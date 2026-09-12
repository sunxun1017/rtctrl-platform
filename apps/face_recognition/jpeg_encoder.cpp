#include "jpeg_encoder.hpp"
#include <climits>
#include <opencv2/imgcodecs.hpp>
#include <stdexcept>
#ifdef RTCTRL_HAVE_TURBOJPEG
#include <dlfcn.h>
#include <turbojpeg.h>
#endif
namespace rtctrl::face {
struct JpegEncoder::Impl {
    bool turbo = false;
#ifdef RTCTRL_HAVE_TURBOJPEG
    void* library = nullptr;
    tjhandle context = nullptr;
    decltype(&tjDestroy) destroy = nullptr;
    decltype(&tjCompress2) compress = nullptr;
    decltype(&tjBufSize) capacity = nullptr;
    decltype(&tjGetErrorStr2) error = nullptr;
    std::vector<unsigned char> buffer;
    int width = 0, height = 0;
    template <class T> T load(const char* name) {
        dlerror();
        auto symbol = dlsym(library, name);
        const char* detail = dlerror();
        if (detail || !symbol)
            throw std::runtime_error(std::string("TurboJPEG missing symbol: ") +
                                     name);
        return reinterpret_cast<T>(symbol);
    }
    void open(const std::string& path) {
        library = dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
        if (!library)
            throw std::runtime_error(std::string("TurboJPEG load failed: ") +
                                     dlerror());
        destroy = load<decltype(destroy)>("tjDestroy");
        compress = load<decltype(compress)>("tjCompress2");
        capacity = load<decltype(capacity)>("tjBufSize");
        error = load<decltype(error)>("tjGetErrorStr2");
        const auto init = load<decltype(&tjInitCompress)>("tjInitCompress");
        context = init();
        if (!context)
            throw std::runtime_error(
                std::string("TurboJPEG initialization failed: ") + error(nullptr));
    }
    ~Impl() {
        if (context)
            destroy(context);
        if (library)
            dlclose(library);
    }
#endif
};
bool JpegEncoder::turbojpeg_compiled() {
#ifdef RTCTRL_HAVE_TURBOJPEG
    return true;
#else
    return false;
#endif
}
JpegEncoder::JpegEncoder(const std::string& encoder, const std::string& library)
    : impl_(std::make_unique<Impl>()) {
    if (encoder == "opencv")
        return;
    if (encoder != "turbojpeg")
        throw std::runtime_error("invalid JPEG encoder: " + encoder);
#ifdef RTCTRL_HAVE_TURBOJPEG
    impl_->open(library);
    impl_->turbo = true;
#else
    (void)library;
    throw std::runtime_error("TurboJPEG support not compiled; configure "
                             "RTCTRL_TURBOJPEG_INCLUDE_DIR or select opencv");
#endif
}
JpegEncoder::~JpegEncoder() = default;
std::vector<unsigned char> JpegEncoder::encode(const cv::Mat& bgr, int quality) {
    if (bgr.empty() || bgr.dims != 2 || bgr.type() != CV_8UC3 || bgr.cols > 8192 ||
        bgr.rows > 8192 || bgr.step > INT_MAX || quality < 1 || quality > 100)
        throw std::runtime_error("invalid JPEG BGR image/quality");
    std::vector<unsigned char> result;
    if (!impl_->turbo) {
        if (!cv::imencode(".jpg", bgr, result, {cv::IMWRITE_JPEG_QUALITY, quality}))
            throw std::runtime_error("JPEG encoding failed");
        return result;
    }
#ifdef RTCTRL_HAVE_TURBOJPEG
    auto& state = *impl_;
    if (state.width != bgr.cols || state.height != bgr.rows) {
        const auto size = state.capacity(bgr.cols, bgr.rows, TJSAMP_420);
        if (size == static_cast<unsigned long>(-1) || !size)
            throw std::runtime_error("TurboJPEG invalid buffer size");
        state.buffer.resize(size);
        state.width = bgr.cols;
        state.height = bgr.rows;
    }
    auto* data = state.buffer.data();
    unsigned long size = state.buffer.size();
    if (state.compress(state.context,
                       bgr.data,
                       bgr.cols,
                       static_cast<int>(bgr.step),
                       bgr.rows,
                       TJPF_BGR,
                       &data,
                       &size,
                       TJSAMP_420,
                       quality,
                       TJFLAG_ACCURATEDCT | TJFLAG_NOREALLOC) != 0)
        throw std::runtime_error(std::string("TurboJPEG encoding failed: ") +
                                 state.error(state.context));
    if (data != state.buffer.data() || !size || size > state.buffer.size())
        throw std::runtime_error("TurboJPEG violated output buffer contract");
    // PreviewServer can retain this frame while the next frame is encoded.
    result.assign(data, data + size);
#endif
    return result;
}
} // namespace rtctrl::face
