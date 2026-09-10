#ifndef RTCTRL_ADAPTERS_RKNN_NATIVE_MEMORY_HPP
#define RTCTRL_ADAPTERS_RKNN_NATIVE_MEMORY_HPP
#include <cstddef>
#include <rknn_api.h>

namespace rknn {
// Native IO only: attr must come from RKNN_QUERY_NATIVE_*_ATTR for this context.
// No type/layout/normalization conversion. Not the Float32 Backend input contract.
// Context must outlive this object. Do not destroy during execution; after binding,
// do not execute the context after destruction until that IO has been rebound.
class NativeMemory final {
  public:
    NativeMemory(rknn_context context, const rknn_tensor_attr& native_attr);
    // Borrows fd and mapping; caller retains both until destruction. capacity is
    // the mapped buffer capacity from its base; offset selects the tensor region.
    NativeMemory(rknn_context context,
                 const rknn_tensor_attr& native_attr,
                 int fd,
                 void* mapping_base,
                 std::size_t capacity,
                 std::size_t offset = 0);
    ~NativeMemory();
    NativeMemory(const NativeMemory&) = delete;
    NativeMemory& operator=(const NativeMemory&) = delete;
    NativeMemory(NativeMemory&&) = delete;
    NativeMemory& operator=(NativeMemory&&) = delete;
    const rknn_tensor_attr& attributes() const noexcept {
        return attr_;
    }
    const rknn_tensor_mem& memory() const noexcept {
        return *memory_;
    }
    // Returns SDK status; failures do not discard owned/imported memory.
    int bind();
    int sync(rknn_mem_sync_mode mode);

  private:
    void validate() const;
    void check_allocation();
    rknn_context context_;
    rknn_tensor_attr attr_;
    rknn_tensor_mem* memory_ = nullptr;
};
} // namespace rknn
#endif
