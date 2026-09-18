#include "aec_bridge.h"
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <memory>
#include <new>
#include <rkaudio_preprocess.h>

namespace {
thread_local char last_error[256]{};
void error(const char* message) {
    std::snprintf(last_error, sizeof(last_error), "%s", message);
}
struct Aec {
    RKAUDIOParam params{};
    SKVAECParameter aec{};
    RKAudioDelayParam delay{};
    SKVPreprocessParam bf{};
    RKAudioAESParameter aes{};
    short channels[2]{0, 1};
    void* state = nullptr;
    bool use_aes = false;
    std::array<short, 512> input{};
    // Guard capacity exceeds the expected mono output. Never expose unvalidated
    // output.
    std::array<short, 1024> output{};
    ~Aec() {
        if (state)
            rkaudio_preprocess_destory(state);
    }
    bool initialize() {
        // Explicit settings: do not inherit SDK header's 8-channel/DOA/AINR
        // defaults.
        delay.MaxFrame = 32;
        delay.LeastDelay = 0;
        delay.JumpFrame = 12;
        delay.DelayOffset = 1;
        delay.MicAmpThr = 50;
        delay.RefAmpThr = 50;
        delay.StartFreq = 500;
        delay.EndFreq = 4000;
        delay.SmoothFactor = .97f;
        aec.pos = 1;
        aec.drop_ref_channel = 0;
        aec.model_aec_en = EN_DELAY;
        aec.delay_len = 0;
        aec.look_ahead = 0;
        aec.Array_list = channels;
        aec.filter_len = 2;
        aec.delay_para = &delay;
        bf.ref_pos = 1;
        bf.num_ref_channel = 1;
        bf.drop_ref_channel = 0;
        bf.Targ = 0;
        bf.model_bf_en = use_aes ? (EN_Fastaec | EN_AES) : 0;
        // Conservative residual suppression; no hard or harmonic suppression.
        aes.Beta_Up = .003f;
        aes.Beta_Down = .002f;
        aes.Beta_Up_Low = .003f;
        aes.Beta_Down_Low = .002f;
        aes.low_freq = 450;
        aes.high_freq = 4000;
        aes.THD_Flag = 0;
        aes.HARD_Flag = 0;
        for (int i = 0; i < 2; i++)
            for (int j = 0; j < 3; j++)
                aes.LimitRatio[i][j] = 1.0f;
        bf.aes_para = &aes;
        params.model_en = RKAUDIO_EN_AEC | (use_aes ? RKAUDIO_EN_BF : 0);
        params.aec_param = &aec;
        params.bf_param = use_aes ? &bf : nullptr;
        params.rx_param = nullptr;
        // SDK convention: interleaved input short count, 256 * (1 mic + 1 ref).
        params.read_size = 512;
        state = rkaudio_preprocess_init(16000, 16, 1, 1, &params);
        if (!state) {
            error("rkaudio initialization failed");
            return false;
        }
        return true;
    }
};
} // namespace
extern "C" {
const char* rtctrl_aec_error(void) {
    return last_error;
}
void* rtctrl_aec_create(int enable_aes) {
    last_error[0] = 0;
    if (enable_aes != 0 && enable_aes != 1) {
        error("enable_aes must be 0 or 1");
        return nullptr;
    }
    std::unique_ptr<Aec> a(new (std::nothrow) Aec);
    if (!a) {
        error("AEC allocation failed");
        return nullptr;
    }
    a->use_aes = enable_aes;
    if (!a->initialize())
        return nullptr;
    return a.release();
}
int rtctrl_aec_process256(void* context,
                          const int16_t* mic,
                          const int16_t* reference,
                          int16_t* output) {
    last_error[0] = 0;
    if (!context || !mic || !reference || !output) {
        error("invalid AEC pointer");
        return -1;
    }
    Aec& a = *static_cast<Aec*>(context);
    if (!a.state) {
        error("AEC context unavailable; reset required");
        return -1;
    }
    for (unsigned i = 0; i < 256; i++) {
        a.input[2 * i] = mic[i];
        a.input[2 * i + 1] = reference[i];
    }
    a.output.fill(static_cast<short>(0x5a6d));
    int wakeup = 0;
    int count = rkaudio_preprocess_short(
        a.state, a.input.data(), a.output.data(), 512, &wakeup);
    if (count != 256 * static_cast<int>(sizeof(int16_t))) {
        std::snprintf(last_error,
                      sizeof(last_error),
                      "unexpected AEC output bytes: %d",
                      count);
        return -1;
    }
    // The BSP returns bytes (512), not sample count. Check that the mono
    // result occupied only the first 256 shorts before exposing caller output.
    if (!std::all_of(a.output.begin() + 256, a.output.end(), [](short value) {
            return value == static_cast<short>(0x5a6d);
        })) {
        error("AEC output exceeded 256 mono samples");
        return -1;
    }
    std::memcpy(output, a.output.data(), 256 * sizeof(int16_t));
    return 0;
}
int rtctrl_aec_reset(void* context) {
    last_error[0] = 0;
    if (!context) {
        error("invalid AEC context");
        return -1;
    }
    Aec& a = *static_cast<Aec*>(context);
    if (a.state) {
        rkaudio_preprocess_destory(a.state);
        a.state = nullptr;
    }
    a.input.fill(0);
    a.output.fill(0);
    return a.initialize() ? 0 : -1;
}
int rtctrl_aec_destroy(void* context) {
    last_error[0] = 0;
    delete static_cast<Aec*>(context);
    return 0;
}
}
