#include "rtctrl/inference/backend.hpp"

#include <array>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>

using namespace rtctrl::inference;

static void check(bool condition) {
    if (!condition) {
        throw std::runtime_error("Test check failed");
    }
}

template <typename Exception, typename Function>
static void expect_throw(Function function) {
    try {
        function();
    } catch (const Exception&) {
        return;
    }
    throw std::runtime_error("Expected exception was not thrown");
}

// A deterministic two-input implementation proves the API is independent of
// hardware. This test does not claim to validate any SDK implementation.
class FakeBackend final : public Backend {
  public:
    std::size_t input_count() const noexcept override {
        return specs_.size();
    }
    const TensorSpec& input_spec(std::size_t index) const override {
        return specs_.at(index);
    }
    MutableTensorView get_input_buffer(std::size_t index) override {
        auto& buffer = buffers_.at(index);
        ready_.at(index) = false;
        return {TensorType::UInt8, buffer.data(), buffer.size()};
    }
    bool commit_input(std::size_t index) override {
        if (index >= input_count()) {
            return false;
        }
        ready_[index] = true;
        return true;
    }
    bool prepare_input_data(const void* data,
                            std::size_t bytes,
                            std::size_t index) override {
        if (index >= input_count()) {
            return false;
        }
        ready_[index] = false;
        if (data == nullptr || bytes != buffers_[index].size()) {
            return false;
        }
        std::memcpy(buffers_[index].data(), data, bytes);
        ready_[index] = true;
        return true;
    }
    bool run() override {
        if (!ready_[0] || !ready_[1]) {
            return false;
        }
        ready_.fill(false);
        result = buffers_[0][0] + buffers_[1][0];
        return true;
    }
    int result = 0;

  private:
    std::array<TensorSpec, 2> specs_{{
        {{2}, TensorType::UInt8, TensorLayout::Undefined},
        {{2}, TensorType::UInt8, TensorLayout::Undefined},
    }};
    std::array<std::array<std::uint8_t, 2>, 2> buffers_{};
    std::array<bool, 2> ready_{};
};

int main() {
    try {
        for (const auto type :
             {TensorType::UInt8, TensorType::Int8, TensorType::Float32}) {
            TensorSpec spec{{2, 3, 4}, type};
            const std::size_t width = type == TensorType::Float32 ? 4U : 1U;
            check(spec.byte_size() == 24 * width);
            spec.shape.clear();
            check(spec.byte_size() == width);
        }
        expect_throw<std::invalid_argument>(
            [] { (void)TensorSpec{{2, 0}, TensorType::Float32}.byte_size(); });
        expect_throw<std::invalid_argument>(
            [] { (void)TensorSpec{{1}, static_cast<TensorType>(99)}.byte_size(); });
        expect_throw<std::overflow_error>([] {
            const auto maximum = std::numeric_limits<std::uint32_t>::max();
            (void)TensorSpec{{maximum, maximum, maximum}, TensorType::Float32}
                .byte_size();
        });

        FakeBackend fake;
        Backend& backend = fake;
        check(backend.input_count() == 2);
        check(backend.input_spec(1).byte_size() == 2);
        expect_throw<std::out_of_range>([&] { (void)backend.input_spec(2); });
        expect_throw<std::out_of_range>([&] { (void)backend.get_input_buffer(2); });
        check(!backend.run());
        std::array<std::uint8_t, 2> first{10, 11};
        check(backend.prepare_input_data(first.data(), first.size(), 0));
        first[0] = 99; // Preparation must copy, not retain the source pointer.
        check(!backend.run()); // The other input is still missing.
        auto second = backend.get_input_buffer(1);
        check(second.type == TensorType::UInt8 && second.size_bytes == 2);
        auto* values = static_cast<std::uint8_t*>(second.data);
        values[0] = 20;
        values[1] = 21;
        check(!backend.run()); // Filling alone is not a commit.
        check(backend.commit_input(1));
        check(backend.run());
        check(fake.result == 30);
        check(!backend.run()); // Each run consumes the prepared set.
        check(!backend.commit_input(2));
        check(!backend.prepare_input_data(first.data(), first.size(), 2));
        check(backend.prepare_input_data(first.data(), first.size(), 0));
        check(!backend.prepare_input_data(nullptr, first.size(), 0));
        check(backend.commit_input(1));
        check(!backend.run()); // Failed update invalidates input 0.
        check(!backend.prepare_input_data(first.data(), 1, 0));
        check(backend.prepare_input_data(first.data(), first.size(), 0));
        (void)backend.get_input_buffer(0);
        check(!backend.run()); // Re-borrowing invalidates prior readiness.
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
    return 0;
}
