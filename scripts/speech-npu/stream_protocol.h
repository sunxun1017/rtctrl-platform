#pragma once
#include <cstdint>
#include <istream>
#include <stdexcept>
#include <string>
#include <vector>
namespace speech_stream {
// Number of 96-frame advances needed to cover real frames, not padded frames.
inline unsigned flush_steps(unsigned processed, unsigned real_frames) {
    return real_frames > processed ? (real_frames - processed + 95) / 96 : 0;
}
struct Request {
    unsigned opcode;
    std::vector<unsigned char> payload;
};
inline bool read_request(std::istream& in, Request& request) {
    unsigned char head[5];
    in.read(reinterpret_cast<char*>(head), 4);
    if (in.gcount() == 0 && in.eof())
        return false;
    if (in.gcount() != 4)
        throw std::runtime_error("truncated header");
    uint32_t size = uint32_t(head[0]) | (uint32_t(head[1]) << 8) |
                    (uint32_t(head[2]) << 16) | (uint32_t(head[3]) << 24);
    if (size > 32000)
        throw std::runtime_error("payload exceeds 32000 bytes");
    if (!in.read(reinterpret_cast<char*>(head + 4), 1))
        throw std::runtime_error("missing opcode");
    request.opcode = head[4];
    if (request.opcode < 1 || request.opcode > 4)
        throw std::runtime_error("unknown opcode");
    if (request.opcode == 1 ? (size == 0 || size % 2) : size != 0)
        throw std::runtime_error("invalid payload length");
    request.payload.resize(size);
    if (size && !in.read(reinterpret_cast<char*>(request.payload.data()), size))
        throw std::runtime_error("truncated payload");
    return true;
}
inline std::string quote(const std::string& value) {
    std::string result = "\"";
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') {
            result += '\\';
            result += char(c);
        } else if (c < 32) {
            const char* hex = "0123456789abcdef";
            result += "\\u00";
            result += hex[c >> 4];
            result += hex[c & 15];
        } else
            result += char(c);
    }
    return result + '"';
}
} // namespace speech_stream
