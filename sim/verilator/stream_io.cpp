#include "stream_io.h"

#include <algorithm>
#include <cstdio>
#include <sstream>
#include <stdexcept>

namespace wavsim {

std::vector<int32_t> read_stream(const std::string& path) {
    std::FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) throw std::runtime_error("cannot open input stream: " + path);

    std::fseek(f, 0, SEEK_END);
    long bytes = std::ftell(f);
    std::fseek(f, 0, SEEK_SET);
    if (bytes < 0) {
        std::fclose(f);
        throw std::runtime_error("cannot size input stream: " + path);
    }
    if (bytes % 4 != 0) {
        std::fclose(f);
        throw std::runtime_error("input stream is not a whole number of int32 samples: " + path);
    }

    std::vector<int32_t> samples(static_cast<size_t>(bytes) / 4);
    if (!samples.empty()) {
        size_t got = std::fread(samples.data(), 4, samples.size(), f);
        if (got != samples.size()) {
            std::fclose(f);
            throw std::runtime_error("short read on input stream: " + path);
        }
    }
    std::fclose(f);
    return samples;
}

void write_stream(const std::string& path, const std::vector<int32_t>& samples) {
    std::FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) throw std::runtime_error("cannot open output stream: " + path);
    if (!samples.empty()) {
        size_t put = std::fwrite(samples.data(), 4, samples.size(), f);
        if (put != samples.size()) {
            std::fclose(f);
            throw std::runtime_error("short write on output stream: " + path);
        }
    }
    std::fclose(f);
}

std::vector<ParamEvent> read_events(const std::string& path) {
    std::FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) throw std::runtime_error("cannot open automation file: " + path);

    std::string text;
    char buf[4096];
    size_t n;
    while ((n = std::fread(buf, 1, sizeof(buf), f)) > 0) text.append(buf, n);
    std::fclose(f);

    std::vector<ParamEvent> events;
    std::istringstream lines(text);
    std::string line;
    int lineno = 0;
    while (std::getline(lines, line)) {
        ++lineno;
        auto hash = line.find('#');
        if (hash != std::string::npos) line.erase(hash);
        std::istringstream fields(line);
        ParamEvent ev{};
        long long value = 0;
        if (!(fields >> ev.sample_index >> ev.param_index >> value)) continue;  // blank
        if (ev.param_index < 0 || ev.param_index > 7) {
            throw std::runtime_error(path + ":" + std::to_string(lineno) +
                                     ": param index must be 0..7");
        }
        if (value < 0 || value > 0xFFFF) {
            throw std::runtime_error(path + ":" + std::to_string(lineno) +
                                     ": value must be 0..65535");
        }
        ev.value = static_cast<uint32_t>(value);
        events.push_back(ev);
    }

    std::stable_sort(events.begin(), events.end(),
                     [](const ParamEvent& a, const ParamEvent& b) {
                         return a.sample_index < b.sample_index;
                     });
    return events;
}

}  // namespace wavsim
