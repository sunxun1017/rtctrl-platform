#include "mpp_jpeg.hpp"
#include <cstring>
#include <stdexcept>
#ifdef RTCTRL_HAVE_MPP_JPEG
#include <im2d.h>
#include <mpp_buffer.h>
#include <mpp_frame.h>
#include <mpp_meta.h>
#include <mpp_packet.h>
#include <mpp_task.h>
#include <rk_mpi.h>
#include <rk_venc_cfg.h>
#endif
namespace rtctrl::face {
#ifdef RTCTRL_HAVE_MPP_JPEG
namespace {
void check(MPP_RET result, const char* operation) {
    if (result)
        throw std::runtime_error(std::string("MPP JPEG ") + operation + ": " +
                                 std::to_string(result));
}
// MPP poll returns a positive ready-task count, unlike other MPP APIs.
void check_poll(MPP_RET result, const char* operation) {
    if (result < 0)
        check(result, operation);
}
struct Session {
    MppCtx context = nullptr;
    MppApi* api = nullptr;
    MppEncCfg config = nullptr;
    MppBufferGroup group = nullptr;
    MppBuffer input = nullptr, output = nullptr;
    MppTask input_task = nullptr; // Dequeued, empty task retained between frames.
    rga_buffer_handle_t source_handle = 0, input_handle = 0;
    std::vector<unsigned char> bgr;
    int width, height, stride, vertical_stride, quality;
    size_t output_capacity;
    Session(int w, int h, int q)
        : width(w)
        , height(h)
        , stride((w + 15) & ~15)
        , vertical_stride((h + 15) & ~15)
        , quality(q)
        , output_capacity(static_cast<size_t>(stride) * vertical_stride * 3) {}
    ~Session() {
        if (context)
            mpp_destroy(context);
        if (source_handle)
            releasebuffer_handle(source_handle);
        if (input_handle)
            releasebuffer_handle(input_handle);
        if (input)
            mpp_buffer_put(input);
        if (output)
            mpp_buffer_put(output);
        if (group)
            mpp_buffer_group_put(group);
        if (config)
            mpp_enc_cfg_deinit(config);
    }
    void init() {
        // Keep DRM buffers non-cacheable. Task-mode output bypasses the
        // cache synchronization performed by encode_get_packet; adding the
        // CACHABLE allocation flag requires explicit CPU-access synchronization.
        check(mpp_buffer_group_get_internal(&group, MPP_BUFFER_TYPE_DRM),
              "buffer group");
        check(mpp_buffer_get(group, &input, output_capacity / 2), "input buffer");
        check(mpp_buffer_get(group, &output, output_capacity), "output buffer");
        bgr.resize(static_cast<size_t>(stride) * height * 3);
        source_handle =
            importbuffer_virtualaddr(bgr.data(), static_cast<int>(bgr.size()));
        input_handle = importbuffer_fd(mpp_buffer_get_fd(input),
                                       static_cast<int>(output_capacity / 2));
        if (!source_handle || !input_handle)
            throw std::runtime_error("MPP JPEG RGA import failed");
        check(mpp_create(&context, &api), "create");
        RK_S64 timeout = 1000;
        check(api->control(context, MPP_SET_OUTPUT_TIMEOUT, &timeout),
              "output timeout");
        check(api->control(context, MPP_SET_INPUT_TIMEOUT, &timeout),
              "input timeout");
        check(mpp_init(context, MPP_CTX_ENC, MPP_VIDEO_CodingMJPEG),
              "initialize encoder");
        check(mpp_enc_cfg_init(&config), "config init");
        check(api->control(context, MPP_ENC_GET_CFG, config), "get config");
        auto set = [&](const char* key, int value) {
            check(mpp_enc_cfg_set_s32(config, key, value), key);
        };
        set("prep:width", width);
        set("prep:height", height);
        set("prep:hor_stride", stride);
        set("prep:ver_stride", vertical_stride);
        set("prep:format", MPP_FMT_YUV420SP);
        set("prep:range", MPP_FRAME_RANGE_JPEG);
        set("codec:type", MPP_VIDEO_CodingMJPEG);
        set("rc:mode", MPP_ENC_RC_MODE_FIXQP);
        set("jpeg:q_factor", quality);
        set("jpeg:qf_min", quality);
        set("jpeg:qf_max", quality);
        check(api->control(context, MPP_ENC_SET_CFG, config), "set config");
    }
    std::vector<unsigned char> encode(const cv::Mat& image) {
        for (int row = 0; row < height; ++row)
            std::memcpy(bgr.data() + static_cast<size_t>(row) * stride * 3,
                        image.ptr(row),
                        static_cast<size_t>(width) * 3);
        auto src = wrapbuffer_handle(
            source_handle, width, height, RK_FORMAT_BGR_888, stride, height);
        auto dst = wrapbuffer_handle(input_handle,
                                     width,
                                     height,
                                     RK_FORMAT_YCbCr_420_SP,
                                     stride,
                                     vertical_stride);
        const auto status = imcvtcolor(src,
                                       dst,
                                       RK_FORMAT_BGR_888,
                                       RK_FORMAT_YCbCr_420_SP,
                                       IM_RGB_TO_YUV_BT601_FULL,
                                       1);
        if (status != IM_STATUS_SUCCESS && status != IM_STATUS_NOERROR)
            throw std::runtime_error(std::string("MPP JPEG RGA conversion: ") +
                                     imStrError(status));
        MppFrame frame = nullptr;
        MppPacket packet = nullptr;
        MppTask output_task = nullptr;
        try {
            check(mpp_frame_init(&frame), "frame init");
            mpp_frame_set_width(frame, width);
            mpp_frame_set_height(frame, height);
            mpp_frame_set_hor_stride(frame, stride);
            mpp_frame_set_ver_stride(frame, vertical_stride);
            mpp_frame_set_fmt(frame, MPP_FMT_YUV420SP);
            mpp_frame_set_buffer(frame, input);
            check(mpp_packet_init_with_buffer(&packet, output), "packet init");
            mpp_packet_set_length(packet, 0);
            if (!input_task) {
                check_poll(api->poll(context,
                                     MPP_PORT_INPUT,
                                     static_cast<MppPollType>(1000)),
                           "poll input");
                check(api->dequeue(context, MPP_PORT_INPUT, &input_task),
                      "dequeue input");
                if (!input_task)
                    throw std::runtime_error("MPP JPEG missing input task");
            }
            check(mpp_task_meta_set_frame(input_task, KEY_INPUT_FRAME, frame),
                  "task frame");
            check(mpp_task_meta_set_packet(input_task, KEY_OUTPUT_PACKET, packet),
                  "task packet");
            check(api->enqueue(context, MPP_PORT_INPUT, input_task),
                  "enqueue input");
            // Explicit successful enqueue is the ownership transfer point.
            input_task = nullptr;
            frame = nullptr;
            packet = nullptr;
            check_poll(
                api->poll(context, MPP_PORT_OUTPUT, static_cast<MppPollType>(1000)),
                "poll output");
            check(api->dequeue(context, MPP_PORT_OUTPUT, &output_task),
                  "dequeue output");
            if (!output_task)
                throw std::runtime_error("MPP JPEG missing output task");
            check(mpp_task_meta_get_packet(output_task, KEY_OUTPUT_PACKET, &packet),
                  "take output packet");
            if (!packet)
                throw std::runtime_error("MPP JPEG missing output packet");
            check(api->enqueue(context, MPP_PORT_OUTPUT, output_task),
                  "return output task");
            output_task = nullptr;
            check_poll(
                api->poll(context, MPP_PORT_INPUT, static_cast<MppPollType>(1000)),
                "poll returned input");
            check(api->dequeue(context, MPP_PORT_INPUT, &input_task),
                  "dequeue returned input");
            if (!input_task)
                throw std::runtime_error("MPP JPEG missing returned input task");
            check(mpp_task_meta_get_frame(input_task, KEY_INPUT_FRAME, &frame),
                  "take returned frame");
            if (!frame)
                throw std::runtime_error("MPP JPEG missing returned frame");
            mpp_frame_deinit(&frame);
            const auto* data =
                static_cast<const unsigned char*>(mpp_packet_get_pos(packet));
            const auto size = mpp_packet_get_length(packet);
            if (!data || !size || size > output_capacity ||
                mpp_packet_is_partition(packet))
                throw std::runtime_error(
                    "MPP JPEG invalid/partitioned output packet");
            // Copy before packet release; HTTP may retain this frame indefinitely.
            std::vector<unsigned char> result(data, data + size);
            mpp_packet_deinit(&packet);
            return result;
        } catch (...) {
            // Dequeued tasks are not in ports. Drain their metadata explicitly;
            // queued/in-flight tasks remain owned and released by mpp_destroy.
            auto reclaim = [&](MppTask task) {
                if (!task)
                    return;
                MppFrame held_frame = nullptr;
                MppPacket held_packet = nullptr;
                mpp_task_meta_get_frame(task, KEY_INPUT_FRAME, &held_frame);
                mpp_task_meta_get_packet(task, KEY_OUTPUT_PACKET, &held_packet);
                if (held_frame && held_frame != frame) {
                    if (frame)
                        mpp_frame_deinit(&frame);
                    frame = held_frame;
                }
                if (held_packet && held_packet != packet) {
                    if (packet)
                        mpp_packet_deinit(&packet);
                    packet = held_packet;
                }
            };
            reclaim(input_task);
            reclaim(output_task);
            mpp_destroy(context);
            context = nullptr;
            input_task = nullptr;
            if (frame)
                mpp_frame_deinit(&frame);
            if (packet)
                mpp_packet_deinit(&packet);
            throw;
        }
    }
};
} // namespace
#endif
struct MppJpegEncoder::Impl {
#ifdef RTCTRL_HAVE_MPP_JPEG
    std::unique_ptr<Session> session;
#endif
};
bool MppJpegEncoder::compiled() {
#ifdef RTCTRL_HAVE_MPP_JPEG
    return true;
#else
    return false;
#endif
}
MppJpegEncoder::MppJpegEncoder()
    : impl_(std::make_unique<Impl>()) {
    if (!compiled())
        throw std::runtime_error("MPP JPEG support not compiled; configure MPP/RGA "
                                 "headers and libraries");
}
MppJpegEncoder::~MppJpegEncoder() = default;
std::vector<unsigned char> MppJpegEncoder::encode(const cv::Mat& image,
                                                  int quality) {
    if (image.empty() || image.dims != 2 || image.type() != CV_8UC3 ||
        image.cols > 8192 || image.rows > 8192 || image.cols % 2 || image.rows % 2 ||
        quality < 1 || quality > 99)
        throw std::runtime_error(
            "MPP JPEG requires even BGR dimensions <=8192 and quality 1..99");
#ifdef RTCTRL_HAVE_MPP_JPEG
    auto& session = impl_->session;
    try {
        if (!session || session->width != image.cols ||
            session->height != image.rows || session->quality != quality) {
            session.reset();
            session = std::make_unique<Session>(image.cols, image.rows, quality);
            session->init();
        }
        return session->encode(image);
    } catch (...) {
        session.reset();
        throw;
    }
#else
    throw std::runtime_error("MPP JPEG support not compiled");
#endif
}
} // namespace rtctrl::face
