#include "preview_server.hpp"
#include <arpa/inet.h>
#include <chrono>
#include <iostream>
#include <stdexcept>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>

namespace {
void check(bool ok, const char* message) {
    if (!ok)
        throw std::runtime_error(message);
}
int connect_to(unsigned short port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    check(fd >= 0, "socket");
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);
    if (connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        close(fd);
        throw std::runtime_error("connect");
    }
    timeval timeout{3, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    return fd;
}
void request(int fd, const std::string& path) {
    std::string req = "GET " + path + " HTTP/1.1\r\nHost: localhost\r\n\r\n";
    check(send(fd, req.data(), req.size(), MSG_NOSIGNAL) ==
              static_cast<ssize_t>(req.size()),
          "request");
}
std::string read_until(int fd, const std::string& marker) {
    std::string result;
    char bytes[8192];
    while (result.find(marker) == std::string::npos) {
        ssize_t n = recv(fd, bytes, sizeof(bytes), 0);
        if (n <= 0)
            break;
        result.append(bytes, static_cast<size_t>(n));
    }
    return result;
}
std::string get(unsigned short port, const std::string& path) {
    int fd = connect_to(port);
    request(fd, path);
    std::string result = read_until(fd, "NEVER_PRESENT_MARKER");
    close(fd);
    return result;
}
} // namespace
int main() {
    using rtctrl::face::PreviewServer;
    try {
        auto server = std::make_unique<PreviewServer>("127.0.0.1", 0);
        auto port = server->port();
        check(port != 0, "ephemeral port");
        bool failed = false;
        try {
            PreviewServer duplicate("127.0.0.1", port);
        } catch (const std::exception&) {
            failed = true;
        }
        check(failed, "bind conflict must fail");
        check(get(port, "/").find("<html lang=") != std::string::npos, "HTML");
        check(get(port, "/snapshot.jpg").find("503") != std::string::npos,
              "no image");
        std::vector<unsigned char> jpeg{0xff, 0xd8, 0x41, 0xff, 0xd9};
        server->publish(jpeg, R"({"running":true,"frame":1})");
        std::string snapshot = get(port, "/snapshot.jpg");
        check(snapshot.find("Content-Length: 5") != std::string::npos,
              "jpeg length");
        check(snapshot.substr(snapshot.size() - 5) ==
                  std::string(jpeg.begin(), jpeg.end()),
              "jpeg bytes");
        server->publish({}, R"({"running":false})");
        check(get(port, "/status.json").find(R"({"running":false})") !=
                  std::string::npos,
              "json update");
        check(get(port, "/snapshot.jpg").find("Content-Length: 5") !=
                  std::string::npos,
              "empty publish preserves image");
        check(get(port, "/../../etc/passwd").find("404") != std::string::npos,
              "fixed routes");
        int stream = connect_to(port);
        request(stream, "/stream.mjpg");
        auto first = read_until(stream, std::string(jpeg.begin(), jpeg.end()));
        check(first.find("multipart/x-mixed-replace") != std::string::npos,
              "stream header");
        check(first.find("Content-Length: 5") != std::string::npos, "stream frame");
        jpeg[2] = 0x42;
        server->publish(jpeg, "{}");
        check(read_until(stream, std::string(jpeg.begin(), jpeg.end()))
                      .find(std::string(jpeg.begin(), jpeg.end())) !=
                  std::string::npos,
              "next frame");
        close(stream);
        std::this_thread::sleep_for(std::chrono::milliseconds(600));
        // A client that reads no JPEG must never hold up the producer.
        int slow = connect_to(port);
        int small = 1024;
        setsockopt(slow, SOL_SOCKET, SO_RCVBUF, &small, sizeof(small));
        request(slow, "/stream.mjpg");
        server->publish(std::vector<unsigned char>(8 * 1024 * 1024, 0x41), "{}");
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        auto start = std::chrono::steady_clock::now();
        for (int i = 0; i < 200; ++i)
            server->publish(jpeg, "{}");
        check(std::chrono::steady_clock::now() - start <
                  std::chrono::milliseconds(500),
              "slow client blocked publish");
        check(get(port, "/status.json").find("{}") != std::string::npos,
              "parallel status");
        // Partial HTTP client exercises shutdown while request read is pending.
        int idle = connect_to(port);
        start = std::chrono::steady_clock::now();
        server.reset();
        check(std::chrono::steady_clock::now() - start < std::chrono::seconds(1),
              "destructor must be bounded");
        close(idle);
        close(slow);
        std::cout << "preview_server tests passed\n";
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
