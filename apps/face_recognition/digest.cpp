#include "digest.hpp"
#include <array>
#include <fstream>
#include <iomanip>
#include <memory>
#include <openssl/evp.h>
#include <sstream>
#include <stdexcept>
namespace rtctrl::face {
std::string model_fingerprint(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input)
        throw std::runtime_error("Cannot hash recognizer model");
    auto free_context = [](EVP_MD_CTX* p) { EVP_MD_CTX_destroy(p); };
    std::unique_ptr<EVP_MD_CTX, decltype(free_context)> ctx(EVP_MD_CTX_create(),
                                                            free_context);
    if (!ctx || EVP_DigestInit_ex(ctx.get(), EVP_sha256(), nullptr) != 1)
        throw std::runtime_error("Cannot initialize SHA256");
    std::array<char, 65536> block{};
    while (input) {
        input.read(block.data(), block.size());
        if (EVP_DigestUpdate(ctx.get(),
                             block.data(),
                             static_cast<std::size_t>(input.gcount())) != 1)
            throw std::runtime_error("SHA256 update failed");
    }
    if (!input.eof())
        throw std::runtime_error("Cannot read recognizer model");
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned int length = 0;
    if (EVP_DigestFinal_ex(ctx.get(), digest, &length) != 1)
        throw std::runtime_error("SHA256 finalization failed");
    std::ostringstream result;
    result << "raw-rgb112-arcface-v1:sha256:" << std::hex << std::setfill('0');
    for (unsigned int i = 0; i < length; ++i)
        result << std::setw(2) << unsigned(digest[i]);
    return result.str();
}
} // namespace rtctrl::face
