#include "rtctrl/adapters/rknn/native_memory.hpp"
#include <iostream>
#include <stdexcept>
namespace {
int created = 0, destroyed = 0, bound = 0, synced = 0;
bool fail = false, short_memory = false;
void require(bool ok) {
    if (!ok)
        throw std::runtime_error("native memory contract failed");
}
template <class F> void rejects(F f) {
    bool threw = false;
    try {
        f();
    } catch (const std::exception&) {
        threw = true;
    }
    require(threw);
}
} // namespace
extern "C" {
rknn_tensor_mem* rknn_create_mem(rknn_context ctx, uint32_t size) {
    require(ctx == 42 && size == 32);
    if (fail)
        return nullptr;
    ++created;
    auto* m = new rknn_tensor_mem{};
    m->size = short_memory ? 16 : size;
    return m;
}
rknn_tensor_mem* rknn_create_mem_from_fd(
    rknn_context ctx, int32_t fd, void* mapping, uint32_t size, int32_t offset) {
    require(fd == 5 && mapping == nullptr && offset == 8);
    return rknn_create_mem(ctx, size);
}
int rknn_destroy_mem(rknn_context ctx, rknn_tensor_mem* m) {
    require(ctx == 42);
    ++destroyed;
    delete m;
    return 0;
}
int rknn_set_io_mem(rknn_context ctx, rknn_tensor_mem* m, rknn_tensor_attr* a) {
    require(ctx == 42 && m->size == 32 && a->pass_through == 1 && a->w_stride == 8);
    ++bound;
    return fail ? -1 : 0;
}
int rknn_mem_sync(rknn_context ctx, rknn_tensor_mem* m, rknn_mem_sync_mode mode) {
    require(ctx == 42 && m->size == 32 && mode == RKNN_MEMORY_SYNC_TO_DEVICE);
    ++synced;
    return fail ? -1 : 0;
}
}
int main() {
    try {
        rknn_tensor_attr attr{};
        attr.n_dims = 4;
        attr.dims[0] = 1;
        attr.dims[1] = 2;
        attr.dims[2] = 3;
        attr.dims[3] = 4;
        attr.n_elems = 24;
        attr.size = 24;
        attr.size_with_stride = 32;
        attr.w_stride = 8;
        attr.type = RKNN_TENSOR_INT8;
        attr.fmt = RKNN_TENSOR_NHWC;
        {
            rknn::NativeMemory memory(42, attr);
            require(memory.attributes().size_with_stride == 32 &&
                    memory.memory().size == 32);
            require(memory.bind() == 0 &&
                    memory.sync(RKNN_MEMORY_SYNC_TO_DEVICE) == 0);
            fail = true;
            require(memory.bind() == -1 &&
                    memory.sync(RKNN_MEMORY_SYNC_TO_DEVICE) == -1);
            fail = false;
        }
        require(created == 1 && destroyed == 1 && bound == 2 && synced == 2);
        {
            rknn::NativeMemory imported(42, attr, 5, nullptr, 40, 8);
            require(imported.bind() == 0);
        }
        require(created == 2 && destroyed == 2);
        rejects([&] { rknn::NativeMemory m(42, attr, 5, nullptr, 39, 8); });
        rejects([&] { rknn::NativeMemory m(42, attr, 5, nullptr, 1, 8); });
        rejects([&] { rknn::NativeMemory m(0, attr); });
        fail = true;
        rejects([&] { rknn::NativeMemory m(42, attr); });
        fail = false;
        short_memory = true;
        rejects([&] { rknn::NativeMemory m(42, attr); });
        require(created == destroyed);
        attr.size_with_stride = 12;
        rejects([&] { rknn::NativeMemory m(42, attr); });
        require(created == destroyed);
        std::cout << "Native memory host contracts passed\n";
    } catch (const std::exception& e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
