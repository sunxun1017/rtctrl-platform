void submit(inference::Backend& backend, const cv::Mat& bgr, int side) {
    require(!bgr.empty() && bgr.type() == CV_8UC3, "expected nonempty BGR8 image");
    require(backend.input_count() == 1, "model must have exactly one input");
    const auto& s = backend.input_spec(0);
    using L = inference::TensorLayout;
    require(s.type == inference::TensorType::Float32 ||
                s.type == inference::TensorType::UInt8,
            "expected float32 or uint8 submission");
    std::vector<std::uint32_t> expected =
        s.layout == L::NCHW
            ? std::vector<std::uint32_t>{1, 3, (unsigned)side, (unsigned)side}
            : std::vector<std::uint32_t>{1, (unsigned)side, (unsigned)side, 3};
    require((s.layout == L::NCHW || s.layout == L::NHWC) && s.shape == expected,
            "unexpected model input shape/layout");
    require(bgr.rows == side && bgr.cols == side, "unexpected image size");
    auto view = backend.get_input_buffer(0);
    require(view.data && view.type == s.type && view.size_bytes == s.byte_size(),
            "invalid writable input view");
    for (int y = 0; y < side; ++y)
        for (int x = 0; x < side; ++x)
            for (int c = 0; c < 3; ++c) {
                auto i = s.layout == L::NCHW ? c * side * side + y * side + x
                                             : (y * side + x) * 3 + c;
                const auto value = bgr.at<cv::Vec3b>(y, x)[2 - c];
                if (s.type == inference::TensorType::Float32)
                    static_cast<float*>(view.data)[i] = value;
                else
                    static_cast<unsigned char*>(view.data)[i] = value;
            }
    require(backend.commit_input(0) && backend.run(), "inference failed");
}
