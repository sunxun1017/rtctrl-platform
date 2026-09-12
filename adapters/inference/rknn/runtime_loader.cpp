// Optional runtime bridge for the executable. Tests supply their own SDK symbols.
// The shared library must match this header, target SoC and installed NPU driver.
#include <rknn_api.h>

#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <iostream>

namespace {
void* runtime() {
    // Keep the library loaded until process exit, so live contexts remain valid.
    static void* library = [] {
        const char* path = std::getenv("RTCTRL_RKNN_RUNTIME");
        void* handle =
            dlopen(path && *path ? path : "librknnrt.so", RTLD_NOW | RTLD_LOCAL);
        if (!handle) {
            std::cerr << "Cannot load RKNN runtime: " << dlerror()
                      << "; set RTCTRL_RKNN_RUNTIME to the matching board library\n";
        }
        if (handle) {
            const char* required[] = {"rknn_init",
                                      "rknn_destroy",
                                      "rknn_query",
                                      "rknn_inputs_set",
                                      "rknn_run",
                                      "rknn_outputs_get",
                                      "rknn_outputs_release"};
            for (const char* name : required) {
                if (!dlsym(handle, name)) {
                    std::cerr << "Incompatible RKNN runtime: missing " << name
                              << '\n';
                    dlclose(handle);
                    return static_cast<void*>(nullptr);
                }
            }
        }
        return handle;
    }();
    return library;
}
template <typename Function> Function symbol(const char* name) {
    void* handle = runtime();
    if (!handle)
        return nullptr;
    void* address = dlsym(handle, name);
    if (!address)
        std::cerr << "Missing RKNN runtime symbol: " << name << '\n';
    Function function = nullptr;
    static_assert(sizeof(function) == sizeof(address),
                  "POSIX function pointer ABI required");
    std::memcpy(&function, &address, sizeof(function));
    return function;
}
} // namespace

extern "C" {
int rknn_init(rknn_context* ctx,
              void* model,
              uint32_t size,
              uint32_t flags,
              rknn_init_extend* extend) {
    static auto function = symbol<decltype(&rknn_init)>("rknn_init");
    return function ? function(ctx, model, size, flags, extend)
                    : RKNN_ERR_DEVICE_UNAVAILABLE;
}
int rknn_destroy(rknn_context ctx) {
    static auto function = symbol<decltype(&rknn_destroy)>("rknn_destroy");
    return function ? function(ctx) : RKNN_ERR_DEVICE_UNAVAILABLE;
}
int rknn_query(rknn_context ctx, rknn_query_cmd command, void* info, uint32_t size) {
    static auto function = symbol<decltype(&rknn_query)>("rknn_query");
    return function ? function(ctx, command, info, size)
                    : RKNN_ERR_DEVICE_UNAVAILABLE;
}
int rknn_inputs_set(rknn_context ctx, uint32_t count, rknn_input inputs[]) {
    static auto function = symbol<decltype(&rknn_inputs_set)>("rknn_inputs_set");
    return function ? function(ctx, count, inputs) : RKNN_ERR_DEVICE_UNAVAILABLE;
}
int rknn_run(rknn_context ctx, rknn_run_extend* extend) {
    static auto function = symbol<decltype(&rknn_run)>("rknn_run");
    return function ? function(ctx, extend) : RKNN_ERR_DEVICE_UNAVAILABLE;
}
int rknn_outputs_get(rknn_context ctx,
                     uint32_t count,
                     rknn_output outputs[],
                     rknn_output_extend* extend) {
    static auto function = symbol<decltype(&rknn_outputs_get)>("rknn_outputs_get");
    return function ? function(ctx, count, outputs, extend)
                    : RKNN_ERR_DEVICE_UNAVAILABLE;
}
int rknn_outputs_release(rknn_context ctx, uint32_t count, rknn_output outputs[]) {
    static auto function =
        symbol<decltype(&rknn_outputs_release)>("rknn_outputs_release");
    return function ? function(ctx, count, outputs) : RKNN_ERR_DEVICE_UNAVAILABLE;
}
rknn_tensor_mem* rknn_create_mem(rknn_context ctx, uint32_t size) {
    static auto function = symbol<decltype(&rknn_create_mem)>("rknn_create_mem");
    return function ? function(ctx, size) : nullptr;
}
rknn_tensor_mem* rknn_create_mem_from_fd(
    rknn_context ctx, int32_t fd, void* mapping, uint32_t size, int32_t offset) {
    static auto function =
        symbol<decltype(&rknn_create_mem_from_fd)>("rknn_create_mem_from_fd");
    return function ? function(ctx, fd, mapping, size, offset) : nullptr;
}
int rknn_destroy_mem(rknn_context ctx, rknn_tensor_mem* mem) {
    static auto function = symbol<decltype(&rknn_destroy_mem)>("rknn_destroy_mem");
    return function ? function(ctx, mem) : RKNN_ERR_DEVICE_UNAVAILABLE;
}
int rknn_set_io_mem(rknn_context ctx, rknn_tensor_mem* mem, rknn_tensor_attr* attr) {
    static auto function = symbol<decltype(&rknn_set_io_mem)>("rknn_set_io_mem");
    return function ? function(ctx, mem, attr) : RKNN_ERR_DEVICE_UNAVAILABLE;
}
int rknn_mem_sync(rknn_context ctx, rknn_tensor_mem* mem, rknn_mem_sync_mode mode) {
    static auto function = symbol<decltype(&rknn_mem_sync)>("rknn_mem_sync");
    return function ? function(ctx, mem, mode) : RKNN_ERR_DEVICE_UNAVAILABLE;
}
}

extern "C" rknn_tensor_mem*
rknn_create_mem2(rknn_context ctx, uint64_t size, uint64_t flags) {
    static auto function = symbol<decltype(&rknn_create_mem2)>("rknn_create_mem2");
    return function ? function(ctx, size, flags) : nullptr;
}
