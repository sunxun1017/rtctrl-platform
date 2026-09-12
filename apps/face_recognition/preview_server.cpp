#include "preview_server.hpp"
#include <arpa/inet.h>
#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <poll.h>
#include <stdexcept>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>

namespace rtctrl::face {
namespace {
constexpr const char* page =
    R"HTML(<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RV1126B 实时人脸识别</title>
<style>body{font:16px system-ui;margin:24px;background:#101824;color:#eef3fa}
main{max-width:1100px;margin:auto}img{width:100%;background:#05080d;border-radius:12px}
pre{white-space:pre-wrap;line-height:1.6}small{color:#b2c2d7}</style>
<main><h1>RV1126B 实时人脸识别</h1><img id="video" src="/stream.mjpg" alt="等待摄像头画面">
<pre id="status">正在连接…</pre><small>相似度不是准确率；unknown 表示未匹配已登记人脸。仅供可信局域网使用。</small></main>
<script>
document.getElementById('video').onerror=function(){setTimeout(()=>{this.src='/stream.mjpg'},1500)};
async function update(){try{let r=await fetch('/status.json',{cache:'no-store'});
if(!r.ok)throw Error('HTTP '+r.status);let s=await r.json();
document.getElementById('status').textContent=
(s.running?'运行中':'等待 / 已停止')+
' | 采集 '+Number(s.capture_fps||0).toFixed(1)+' FPS'+
' | 识别 '+Number(s.fps||0).toFixed(1)+' FPS'+
' | 发布 '+Number(s.publish_fps||0).toFixed(1)+' FPS'+
'\n转换 '+Number(s.capture_convert_ms||0).toFixed(1)+' ms'+
' | 推理 '+Number(s.processing_ms||0).toFixed(1)+' ms'+
' | JPEG '+Number(s.encode_ms||0).toFixed(1)+' ms'+
' | 发布前帧龄 '+Number(s.ready_age_ms||0).toFixed(0)+' ms'+
'\n采集序号缺口 '+(s.capture_sequence_gaps||0)+
' | 待识别覆盖 '+(s.latest_overwrites||0)+
' | 待编码覆盖 '+(s.encode_overwrites||0)+
' | 已识别 '+(s.processed||0)+' | 已发布 '+(s.published||0)+'\n'+
(s.faces||[]).map(f=>(f.name||'unknown')+'  相似度 '+Number(f.similarity||0).toFixed(3)).join('\n')+
(s.note?'\n'+s.note:'');
}catch(e){document.getElementById('status').textContent='连接中断：'+e.message}
setTimeout(update,1000)}update();
</script></html>)HTML";

bool send_all(int fd, const void* data, size_t size) {
    const auto* p = static_cast<const char*>(data);
    // A total deadline, not just SO_SNDTIMEO: dribbling readers are bounded too.
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (size) {
        if (std::chrono::steady_clock::now() >= deadline)
            return false;
        ssize_t n = send(fd, p, size, MSG_NOSIGNAL | MSG_DONTWAIT);
        if (n > 0) {
            p += n;
            size -= static_cast<size_t>(n);
            continue;
        }
        if (n < 0 && errno == EINTR)
            continue;
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            pollfd poller{fd, POLLOUT, 0};
            if (poll(&poller, 1, 100) >= 0)
                continue;
            if (errno == EINTR)
                continue;
        }
        return false;
    }
    return true;
}
bool send_text(int fd, const std::string& s) {
    return send_all(fd, s.data(), s.size());
}
bool response(int fd,
              const std::string& code,
              const std::string& type,
              const void* data,
              size_t size) {
    return send_text(fd,
                     "HTTP/1.1 " + code + "\r\nContent-Type: " + type +
                         "\r\nCache-Control: no-store\r\nX-Content-Type-Options: "
                         "nosniff\r\nConnection: close\r\nContent-Length: " +
                         std::to_string(size) + "\r\n\r\n") &&
           send_all(fd, data, size);
}
} // namespace

struct PreviewServer::Impl {
    struct Frame {
        std::vector<unsigned char> jpeg;
        uint64_t sequence = 0;
    };
    struct Client {
        int fd = -1;
        std::thread thread;
    };
    int listener = -1;
    unsigned short bound_port = 0;
    std::atomic<bool> stopping{false};
    std::thread accept_thread;
    std::mutex clients_mutex;
    std::array<Client, 4> clients;
    std::mutex frame_mutex;
    std::condition_variable changed;
    std::shared_ptr<const Frame> latest;
    std::string json = R"({"running":false,"note":"等待第一帧"})";
    uint64_t sequence = 0;

    Impl(const std::string& address, unsigned short port) {
        listener = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
        if (listener < 0)
            throw std::runtime_error("preview socket: " +
                                     std::string(strerror(errno)));
        try {
            int one = 1;
            setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
            sockaddr_in addr{};
            addr.sin_family = AF_INET;
            addr.sin_port = htons(port);
            if (inet_pton(AF_INET, address.c_str(), &addr.sin_addr) != 1)
                throw std::runtime_error(
                    "preview bind address must be an IPv4 literal");
            if (bind(listener, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) <
                    0 ||
                listen(listener, 4) < 0)
                throw std::runtime_error("preview bind/listen: " +
                                         std::string(strerror(errno)));
            socklen_t size = sizeof(addr);
            if (getsockname(listener, reinterpret_cast<sockaddr*>(&addr), &size) < 0)
                throw std::runtime_error("preview getsockname failed");
            bound_port = ntohs(addr.sin_port);
            accept_thread = std::thread([this] { accept_loop(); });
        } catch (...) {
            close(listener);
            listener = -1;
            throw;
        }
    }

    ~Impl() {
        stopping = true;
        changed.notify_all();
        // accept_loop polls at most 100 ms; listener stays owned until it exits.
        if (accept_thread.joinable())
            accept_thread.join();
        close(listener);
        {
            std::lock_guard<std::mutex> lock(clients_mutex);
            for (auto& c : clients)
                if (c.fd >= 0)
                    shutdown(c.fd, SHUT_RDWR);
        }
        for (auto& c : clients)
            if (c.thread.joinable())
                c.thread.join();
    }

    void accept_loop() {
        while (!stopping) {
            pollfd p{listener, POLLIN, 0};
            if (poll(&p, 1, 100) <= 0 || !(p.revents & POLLIN))
                continue;
            int fd = accept4(listener, nullptr, nullptr, SOCK_CLOEXEC);
            if (fd < 0)
                continue;
            timeval timeout{2, 0};
            setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
            setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
            std::lock_guard<std::mutex> lock(clients_mutex);
            Client* slot = nullptr;
            for (auto& c : clients)
                if (c.fd < 0) {
                    slot = &c;
                    break;
                }
            if (!slot) {
                close(fd);
                continue;
            }
            if (slot->thread.joinable())
                slot->thread.join();
            slot->fd = fd;
            try {
                slot->thread = std::thread([this, slot, fd] {
                    try {
                        serve(fd);
                    } catch (...) { /* Disconnect failed client. */
                    }
                    std::lock_guard<std::mutex> done(clients_mutex);
                    close(fd);
                    slot->fd = -1;
                });
            } catch (...) {
                close(fd);
                slot->fd = -1;
            }
        }
    }

    void serve(int fd) {
        std::string request;
        auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        while (request.find("\r\n\r\n") == std::string::npos) {
            if (stopping || request.size() >= 4096 ||
                std::chrono::steady_clock::now() >= deadline)
                return;
            char buf[512];
            pollfd p{fd, POLLIN, 0};
            if (poll(&p, 1, 100) <= 0)
                continue;
            ssize_t n = recv(fd, buf, sizeof(buf), MSG_DONTWAIT);
            if (n <= 0)
                return;
            request.append(buf, static_cast<size_t>(n));
        }
        auto end = request.find("\r\n");
        std::string line = request.substr(0, end);
        auto path_end = line.find(' ', 4);
        if (line.compare(0, 4, "GET ") != 0 || path_end == std::string::npos) {
            response(fd, "405 Method Not Allowed", "text/plain", "GET only", 8);
            return;
        }
        std::string path = line.substr(4, path_end - 4);
        if (path == "/") {
            response(fd, "200 OK", "text/html; charset=utf-8", page, strlen(page));
            return;
        }
        if (path == "/status.json") {
            std::string copy;
            {
                std::lock_guard<std::mutex> lock(frame_mutex);
                copy = json;
            }
            response(fd,
                     "200 OK",
                     "application/json; charset=utf-8",
                     copy.data(),
                     copy.size());
            return;
        }
        if (path == "/snapshot.jpg") {
            std::shared_ptr<const Frame> frame;
            {
                std::lock_guard<std::mutex> lock(frame_mutex);
                frame = latest;
            }
            if (frame)
                response(fd,
                         "200 OK",
                         "image/jpeg",
                         frame->jpeg.data(),
                         frame->jpeg.size());
            else
                response(fd, "503 Service Unavailable", "text/plain", "No frame", 8);
            return;
        }
        if (path != "/stream.mjpg") {
            response(fd, "404 Not Found", "text/plain", "Not found", 9);
            return;
        }
        if (!send_text(fd,
                       "HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; "
                       "boundary=frame\r\nCache-Control: no-store\r\nConnection: "
                       "close\r\n\r\n"))
            return;
        uint64_t sent = 0;
        while (!stopping) {
            std::shared_ptr<const Frame> frame;
            {
                std::unique_lock<std::mutex> lock(frame_mutex);
                changed.wait_for(lock, std::chrono::milliseconds(500), [&] {
                    return stopping || (latest && latest->sequence != sent);
                });
                if (stopping)
                    return;
                if (!latest || latest->sequence == sent) {
                    lock.unlock();
                    // Reclaim idle disconnected streams even before the next frame.
                    char probe;
                    auto n = recv(fd, &probe, 1, MSG_PEEK | MSG_DONTWAIT);
                    if (n == 0 || (n < 0 && errno != EAGAIN &&
                                   errno != EWOULDBLOCK && errno != EINTR))
                        return;
                    continue;
                }
                frame = latest;
            }
            if (!send_text(
                    fd,
                    "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                        std::to_string(frame->jpeg.size()) + "\r\n\r\n") ||
                !send_all(fd, frame->jpeg.data(), frame->jpeg.size()) ||
                !send_text(fd, "\r\n"))
                return;
            sent = frame->sequence;
        }
    }
};

PreviewServer::PreviewServer(const std::string& address, unsigned short port)
    : impl_(std::make_unique<Impl>(address, port)) {}
PreviewServer::~PreviewServer() = default;
unsigned short PreviewServer::port() const {
    return impl_->bound_port;
}
void PreviewServer::publish(std::vector<unsigned char> jpeg, std::string json) {
    if (jpeg.size() > 16 * 1024 * 1024 || json.size() > 64 * 1024)
        throw std::length_error(
            "preview frame exceeds 16 MiB or JSON exceeds 64 KiB");
    std::shared_ptr<Impl::Frame> frame;
    if (!jpeg.empty()) {
        frame = std::make_shared<Impl::Frame>();
        frame->jpeg = std::move(jpeg);
    }
    {
        std::lock_guard<std::mutex> lock(impl_->frame_mutex);
        impl_->json = std::move(json);
        if (frame) {
            frame->sequence = ++impl_->sequence;
            impl_->latest = std::move(frame);
        }
    }
    impl_->changed.notify_all();
}
} // namespace rtctrl::face
