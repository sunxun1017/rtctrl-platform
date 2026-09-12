#include "mpp_jpeg.hpp"
#include <im2d.h>
#include <iostream>
#include <map>
#include <mpp_buffer.h>
#include <mpp_frame.h>
#include <mpp_meta.h>
#include <mpp_packet.h>
#include <mpp_task.h>
#include <rk_mpi.h>
#include <rk_venc_cfg.h>
#include <stdexcept>
static int live = 0, allocations = 0, failure = 0;
static unsigned serial = 0;
static std::map<unsigned, void*> imports;
static unsigned char output_bytes[3];
static MppPacket pending = nullptr;
struct FakeTask {
    MppFrame frame = nullptr;
    MppPacket packet = nullptr;
};
static FakeTask input_task, output_task;
static bool input_queued = true, output_queued = false, has_submitted = false;
void* create() {
    ++live;
    return new int(0);
}
void destroy(void* p) {
    if (p) {
        --live;
        delete static_cast<int*>(p);
    }
}
void require(bool b) {
    if (!b)
        throw std::runtime_error("MPP mock assertion");
}
MPP_RET mpp_buffer_group_get(
    MppBufferGroup* g, MppBufferType, MppBufferMode, const char*, const char*) {
    *g = create();
    return MPP_OK;
}
MPP_RET mpp_buffer_group_put(MppBufferGroup g) {
    destroy(g);
    return MPP_OK;
}
MPP_RET mpp_buffer_get_with_tag(
    MppBufferGroup, MppBuffer* b, size_t, const char*, const char*) {
    *b = create();
    ++allocations;
    return MPP_OK;
}
MPP_RET mpp_buffer_put_with_caller(MppBuffer b, const char*) {
    destroy(b);
    return MPP_OK;
}
int mpp_buffer_get_fd_with_caller(MppBuffer, const char*) {
    return 17;
}
rga_buffer_handle_t importbuffer_virtualaddr(void* p, int) {
    imports[++serial] = p;
    return serial;
}
rga_buffer_handle_t importbuffer_fd(int, int) {
    if (failure == 1)
        return 0;
    imports[++serial] = nullptr;
    return serial;
}
IM_STATUS releasebuffer_handle(rga_buffer_handle_t h) {
    imports.erase(h);
    return IM_STATUS_SUCCESS;
}
rga_buffer_t wrapbuffer_handle(
    rga_buffer_handle_t h, int w, int height, int format, int ws, int hs) {
    rga_buffer_t r{};
    r.handle = h;
    r.width = w;
    r.height = height;
    r.format = format;
    r.wstride = ws;
    r.hstride = hs;
    return r;
}
const char* imStrError_t(IM_STATUS) {
    return "mock RGA failure";
}
IM_STATUS imcvtcolor(
    rga_buffer_t src, rga_buffer_t dst, int sf, int df, int mode, int sync, int*) {
    require(sf == RK_FORMAT_BGR_888 && df == RK_FORMAT_YCbCr_420_SP &&
            mode == IM_RGB_TO_YUV_BT601_FULL && sync == 1);
    require(dst.wstride % 16 == 0 && dst.hstride % 16 == 0);
    auto* p = static_cast<unsigned char*>(imports.at(src.handle)) +
              (src.height - 1) * src.wstride * 3;
    for (int i = 0; i < 3; ++i)
        output_bytes[i] = p[i];
    return IM_STATUS_SUCCESS;
}
MPP_RET mpp_enc_cfg_init(MppEncCfg* c) {
    *c = create();
    return MPP_OK;
}
MPP_RET mpp_enc_cfg_deinit(MppEncCfg c) {
    destroy(c);
    return MPP_OK;
}
MPP_RET mpp_enc_cfg_set_s32(MppEncCfg, const char*, RK_S32) {
    return failure == 5 ? MPP_NOK : MPP_OK;
}
MPP_RET mpp_frame_init(MppFrame* f) {
    *f = create();
    return MPP_OK;
}
MPP_RET mpp_frame_deinit(MppFrame* f) {
    destroy(*f);
    *f = nullptr;
    return MPP_OK;
}
void mpp_frame_set_width(MppFrame, RK_U32) {}
void mpp_frame_set_height(MppFrame, RK_U32) {}
void mpp_frame_set_hor_stride(MppFrame, RK_U32) {}
void mpp_frame_set_ver_stride(MppFrame, RK_U32) {}
void mpp_frame_set_fmt(MppFrame, MppFrameFormat) {}
void mpp_frame_set_buffer(MppFrame, MppBuffer) {}
MppMeta mpp_frame_get_meta(const MppFrame f) {
    return f;
}
MPP_RET mpp_meta_set_packet(MppMeta, MppMetaKey, MppPacket p) {
    pending = p;
    return MPP_OK;
}
MPP_RET mpp_packet_init_with_buffer(MppPacket* p, MppBuffer) {
    *p = create();
    return MPP_OK;
}
MPP_RET mpp_packet_deinit(MppPacket* p) {
    destroy(*p);
    *p = nullptr;
    return MPP_OK;
}
void mpp_packet_set_length(MppPacket, size_t n) {
    require(n == 0);
}
void* mpp_packet_get_pos(const MppPacket) {
    return output_bytes;
}
size_t mpp_packet_get_length(const MppPacket) {
    return failure == 3 ? 0 : 3;
}
RK_U32 mpp_packet_is_partition(const MppPacket) {
    return failure == 4;
}
MPP_RET control(MppCtx, MpiCmd cmd, MppParam param) {
    if (cmd == MPP_SET_OUTPUT_TIMEOUT || cmd == MPP_SET_INPUT_TIMEOUT)
        require(*static_cast<RK_S64*>(param) == 1000);
    return MPP_OK;
}
MPP_RET mpp_task_meta_set_frame(MppTask t, MppMetaKey, MppFrame f) {
    static_cast<FakeTask*>(t)->frame = f;
    return MPP_OK;
}
MPP_RET mpp_task_meta_set_packet(MppTask t, MppMetaKey, MppPacket p) {
    static_cast<FakeTask*>(t)->packet = p;
    return MPP_OK;
}
MPP_RET mpp_task_meta_get_frame(MppTask t, MppMetaKey, MppFrame* f) {
    auto& value = static_cast<FakeTask*>(t)->frame;
    *f = value;
    value = nullptr;
    return *f ? MPP_OK : MPP_NOK;
}
MPP_RET mpp_task_meta_get_packet(MppTask t, MppMetaKey, MppPacket* p) {
    auto& value = static_cast<FakeTask*>(t)->packet;
    *p = value;
    value = nullptr;
    return *p ? MPP_OK : MPP_NOK;
}
MPP_RET poll(MppCtx, MppPortType port, MppPollType timeout) {
    require(static_cast<int>(timeout) == 1000);
    if (port == MPP_PORT_OUTPUT && failure == 2)
        return MPP_NOK;
    if (port == MPP_PORT_INPUT && has_submitted && failure == 8)
        return MPP_NOK;
    return static_cast<MPP_RET>(1);
}
MPP_RET dequeue(MppCtx, MppPortType port, MppTask* task) {
    if (port == MPP_PORT_OUTPUT) {
        if (failure == 6) {
            *task = nullptr;
            return MPP_OK;
        }
        require(output_queued);
        output_queued = false;
        *task = &output_task;
    } else {
        require(input_queued);
        input_queued = false;
        *task = &input_task;
    }
    return MPP_OK;
}
MPP_RET enqueue(MppCtx, MppPortType port, MppTask task) {
    if (port == MPP_PORT_INPUT) {
        if (failure == 7)
            return MPP_NOK;
        require(task == &input_task && input_task.frame && input_task.packet);
        output_task.packet = input_task.packet;
        input_task.packet = nullptr;
        input_queued = true;
        output_queued = true;
        has_submitted = true;
    } else {
        if (failure == 9)
            return MPP_NOK;
        require(task == &output_task && !output_task.packet);
    }
    return MPP_OK;
}
MPP_RET mpp_create(MppCtx* c, MppApi** a) {
    static MppApi api{};
    api.control = control;
    api.poll = poll;
    api.dequeue = dequeue;
    api.enqueue = enqueue;
    input_task = {};
    output_task = {};
    input_queued = true;
    output_queued = false;
    has_submitted = false;
    *a = &api;
    *c = create();
    return MPP_OK;
}
MPP_RET mpp_init(MppCtx, MppCtxType, MppCodingType type) {
    require(type == MPP_VIDEO_CodingMJPEG);
    return MPP_OK;
}
MPP_RET mpp_destroy(MppCtx c) {
    // Mimic release_task_in_port: SDK frees queued refs; caller must drain held
    // tasks.
    if (input_queued) {
        if (input_task.frame)
            mpp_frame_deinit(&input_task.frame);
        if (input_task.packet)
            mpp_packet_deinit(&input_task.packet);
    }
    if (output_queued && output_task.packet)
        mpp_packet_deinit(&output_task.packet);
    require(!input_task.frame && !input_task.packet && !output_task.packet);
    destroy(c);
    return MPP_OK;
}
template <class F> void rejects(F f) {
    bool failed = false;
    try {
        f();
    } catch (const std::runtime_error&) {
        failed = true;
    }
    require(failed);
}
int main() {
    try {
        {
            rtctrl::face::MppJpegEncoder e;
            rejects([&] { e.encode({}, 75); });
            rejects([&] { e.encode(cv::Mat(2, 3, CV_8UC3), 75); });
            cv::Mat parent(8, 28, CV_8UC3, cv::Scalar(99, 99, 99));
            auto roi = parent(cv::Rect(2, 2, 18, 4));
            roi.setTo(cv::Scalar(1, 2, 3));
            auto first = e.encode(roi, 75);
            int allocated = allocations;
            roi.setTo(cv::Scalar(4, 5, 6));
            auto next = e.encode(roi, 75);
            require(first == std::vector<unsigned char>({1, 2, 3}) &&
                    next == std::vector<unsigned char>({4, 5, 6}) &&
                    allocations == allocated);
            e.encode(roi, 80);
            require(allocations == allocated + 2);
            for (int mode = 1; mode <= 9; ++mode) {
                failure = mode; // Force a fresh init for import/config failures.
                rejects([&] { e.encode(roi, 60 + mode); });
                require(live == 0 && imports.empty());
                failure = 0;
                e.encode(roi, 75);
            }
        }
        require(live == 0 && imports.empty());
        std::cout << "MPP JPEG mock tests passed\n";
    } catch (const std::exception& e) {
        std::cerr << e.what() << "\n";
        return 1;
    }
}
