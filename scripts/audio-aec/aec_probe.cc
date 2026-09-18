// Synthetic-only offline probe: no ALSA, microphone, playback, files, or networking.
#include "aec_bridge.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
int main(int argc, char** argv) {
    int aes = argc > 1 ? std::atoi(argv[1]) : 0;
    void* a = rtctrl_aec_create(aes);
    if (!a) {
        std::fprintf(stderr, "%s\n", rtctrl_aec_error());
        return 1;
    }
    const unsigned count = 16000 * 12, delay = 800;
    std::vector<int16_t> ref(count), mic(count), out(count), near(count);
    uint32_t rng = 37;
    double filtered = 0;
    for (unsigned i = 0; i < count; i++) {
        rng = 1664525 * rng + 1013904223;
        filtered = .7 * filtered + .3 * (int(rng >> 16) - 32768);
        ref[i] = static_cast<int16_t>(filtered * .5);
        near[i] = i >= 16000 * 8
                      ? static_cast<int16_t>(2200 * std::sin(2 * 3.141592653589793 *
                                                             347 * i / 16000.0))
                      : 0;
        mic[i] =
            static_cast<int16_t>((i >= delay ? ref[i - delay] * .6 : 0) + near[i]);
    }
    for (unsigned i = 0; i < count; i += 256) {
        if (rtctrl_aec_process256(
                a, mic.data() + i, ref.data() + i, out.data() + i)) {
            std::fprintf(stderr, "frame=%u %s\n", i / 256, rtctrl_aec_error());
            rtctrl_aec_destroy(a);
            return 2;
        }
    }
    double before = 0, after = 0;
    for (unsigned i = 16000 * 5; i < 16000 * 8; i++) {
        before += double(mic[i]) * mic[i];
        after += double(out[i]) * out[i];
    }
    // Output algorithmic latency is unknown: report best near-end tone amplitude,
    // invariant to a fixed phase/delay. This is synthetic preservation, not speech
    // quality.
    double sinpart = 0, cospart = 0;
    for (unsigned i = 16000 * 9; i < count; i++) {
        double angle = 2 * 3.141592653589793 * 347 * i / 16000.0;
        sinpart += out[i] * std::sin(angle);
        cospart += out[i] * std::cos(angle);
    }
    double amp =
        2 * std::sqrt(sinpart * sinpart + cospart * cospart) / (count - 16000 * 9);
    std::printf("{\"aes\":%d,\"synthetic_erle_db\":%.3f,\"near_tone_gain\":%.4f}\n",
                aes,
                10 * std::log10((before + 1) / (after + 1)),
                amp / 2200);
    int rc = rtctrl_aec_reset(a);
    rtctrl_aec_destroy(a);
    return rc ? 3 : 0;
}
