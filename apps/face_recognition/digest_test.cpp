#include "digest.hpp"
#include <cstdio>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <unistd.h>

int main() {
    char path[] = "/tmp/rtctrl-digest-XXXXXX";
    int fd = mkstemp(path);
    if (fd < 0)
        return 1;
    close(fd);
    try {
        {
            std::ofstream out(path);
            out << "abc";
        }
        if (rtctrl::face::model_fingerprint(path) !=
            "raw-rgb112-arcface-v1:sha256:"
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
            throw std::runtime_error("SHA256 mismatch");
        std::remove(path);
        try {
            (void)rtctrl::face::model_fingerprint(path);
        } catch (const std::runtime_error&) {
            return 0;
        }
        throw std::runtime_error("Missing file accepted");
    } catch (const std::exception& e) {
        std::remove(path);
        std::cerr << e.what() << '\n';
        return 1;
    }
}
