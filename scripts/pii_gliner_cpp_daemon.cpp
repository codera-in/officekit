#include <algorithm>
#include <cctype>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include <onnxruntime_cxx_api.h>
#include "GLiNER/gliner.hpp"

namespace {

std::string decode_base64(const std::string& input) {
    static const std::string alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string output;
    int value = 0;
    int bits = -8;
    for (unsigned char character : input) {
        if (character == '=') break;
        const auto position = alphabet.find(static_cast<char>(character));
        if (position == std::string::npos) throw std::runtime_error("invalid base64 request");
        value = (value << 6) | static_cast<int>(position);
        bits += 6;
        if (bits >= 0) {
            output.push_back(static_cast<char>((value >> bits) & 0xFF));
            bits -= 8;
        }
    }
    return output;
}

std::vector<std::pair<size_t, std::string>> windows(const std::string& text) {
    constexpr size_t window_chars = 1200;
    constexpr size_t overlap_chars = 240;
    std::vector<std::pair<size_t, std::string>> result;
    size_t start = 0;
    while (start < text.size()) {
        size_t end = std::min(text.size(), start + window_chars);
        if (end < text.size()) {
            const size_t boundary = text.rfind(' ', end);
            if (boundary != std::string::npos && boundary > start + window_chars / 2) end = boundary;
            while (end > start && (static_cast<unsigned char>(text[end]) & 0xC0) == 0x80) --end;
        }
        if (end <= start) throw std::runtime_error("unable to create a valid UTF-8 text window");
        result.emplace_back(start, text.substr(start, end - start));
        if (end == text.size()) break;
        size_t next = end > overlap_chars ? end - overlap_chars : end;
        while (next < end && (static_cast<unsigned char>(text[next]) & 0xC0) == 0x80) ++next;
        const size_t boundary = text.find(' ', next);
        start = boundary != std::string::npos && boundary < end ? boundary + 1 : next;
    }
    return result;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 4) return 2;
    try {
        const std::string model_path = argv[1];
        const std::string tokenizer_path = argv[2];
        const int threads = std::stoi(argv[3]);
        if (threads < 1 || threads > 4) return 2;

        Ort::Env env(ORT_LOGGING_LEVEL_ERROR, "officekit-local-pii");
        Ort::SessionOptions options;
        options.SetIntraOpNumThreads(threads);
        options.SetInterOpNumThreads(threads);
        const gliner::Config config{12, 512, gliner::ModelType::TOKEN_LEVEL};
        gliner::Model model(model_path, tokenizer_path, config, env, options);
        const std::vector<std::string> labels = {
            "name", "dob", "email address", "phone number", "ip address", "location address",
            "account number", "bank account", "credit card", "ssn", "passport number", "username"
        };
        std::cout << "READY\n" << std::flush;

        std::string request;
        while (std::getline(std::cin, request)) {
            try {
                const auto separator = request.find('\t');
                if (separator == std::string::npos) throw std::runtime_error("malformed request");
                const float threshold = std::stof(request.substr(0, separator));
                if (threshold < 0.0f || threshold > 1.0f) throw std::runtime_error("invalid threshold");
                const std::string text = decode_base64(request.substr(separator + 1));
                size_t count = 0;
                for (const auto& [offset, window] : windows(text)) {
                    const auto batches = model.inference({window}, labels, true, threshold);
                    for (const auto& span : batches.at(0)) {
                        std::cout << span.classLabel << '\t' << offset + static_cast<size_t>(span.startIdx)
                                  << '\t' << offset + static_cast<size_t>(span.endIdx) << '\t'
                                  << span.prob << '\n';
                        if (++count > 2000) throw std::runtime_error("too many results");
                    }
                }
            } catch (const std::exception&) {
                std::cout << "ERROR\tdetection failed\n";
            }
            std::cout << ".\n" << std::flush;
        }
    } catch (const std::exception& error) {
        std::cerr << "local PII runtime startup failed: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
