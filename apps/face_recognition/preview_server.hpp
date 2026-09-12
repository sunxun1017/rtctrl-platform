#pragma once
#include <memory>
#include <string>
#include <vector>
namespace rtctrl::face {
// IPv4 HTTP preview server. publish() never waits for network clients.
class PreviewServer {
  public:
    PreviewServer(const std::string& bind_address, unsigned short port);
    ~PreviewServer();
    PreviewServer(const PreviewServer&) = delete;
    PreviewServer& operator=(const PreviewServer&) = delete;
    // Empty jpeg preserves the last image and updates JSON only.
    void publish(std::vector<unsigned char> jpeg, std::string json);
    unsigned short port() const;

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace rtctrl::face
