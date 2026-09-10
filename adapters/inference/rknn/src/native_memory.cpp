#include "rtctrl/adapters/rknn/native_memory.hpp"
#include <cstdint>
#include <limits>
#include <stdexcept>
namespace rknn {
void NativeMemory::validate() const {
    if (context_ == 0 || attr_.n_dims == 0 || attr_.n_dims > RKNN_MAX_DIMS ||
        attr_.n_elems == 0 || attr_.size == 0 ||
        attr_.size_with_stride < attr_.size) {
        throw std::invalid_argument("Invalid native RKNN tensor metadata");
    }
    for (std::uint32_t i = 0; i < attr_.n_dims; ++i)
        if (attr_.dims[i] == 0)
            throw std::invalid_argument("Dynamic/empty native shape unsupported");
}
void NativeMemory::check_allocation() {
    if (!memory_)
        throw std::runtime_error("RKNN native memory creation failed");
    if (memory_->size < attr_.size_with_stride) {
        rknn_destroy_mem(context_, memory_);
        memory_ = nullptr;
        throw std::runtime_error("RKNN native memory capacity too small");
    }
}
NativeMemory::NativeMemory(rknn_context context, const rknn_tensor_attr& attr)
    : context_(context)
    , attr_(attr) {
    validate();
    attr_.pass_through = 1;
    memory_ = rknn_create_mem(context_, attr_.size_with_stride);
    check_allocation();
}
NativeMemory::NativeMemory(rknn_context context,
                           const rknn_tensor_attr& attr,
                           int fd,
                           void* mapping,
                           std::size_t capacity,
                           std::size_t offset)
    : context_(context)
    , attr_(attr) {
    validate();
    if (fd < 0 ||
        offset >
            static_cast<std::size_t>(std::numeric_limits<std::int32_t>::max()) ||
        offset > capacity || capacity - offset < attr_.size_with_stride) {
        throw std::invalid_argument(
            "Invalid native RKNN imported buffer capacity/offset");
    }
    attr_.pass_through = 1;
    memory_ = rknn_create_mem_from_fd(context_,
                                      fd,
                                      mapping,
                                      attr_.size_with_stride,
                                      static_cast<std::int32_t>(offset));
    check_allocation();
}
NativeMemory::~NativeMemory() {
    if (memory_)
        rknn_destroy_mem(context_, memory_);
}
int NativeMemory::bind() {
    return rknn_set_io_mem(context_, memory_, &attr_);
}
int NativeMemory::sync(rknn_mem_sync_mode mode) {
    if (mode != RKNN_MEMORY_SYNC_TO_DEVICE && mode != RKNN_MEMORY_SYNC_FROM_DEVICE &&
        mode != RKNN_MEMORY_SYNC_BIDIRECTIONAL)
        throw std::invalid_argument("Invalid RKNN memory synchronization mode");
    return rknn_mem_sync(context_, memory_, mode);
}
} // namespace rknn
