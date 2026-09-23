// Sample-stream and parameter-automation file I/O for the Verilator harness.
// Format is documented in sim/STREAM_FORMAT.md.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace wavsim {

// One scheduled parameter change: at input sample `sample_index`, write
// `value` into parameter slot `param_index`.
struct ParamEvent {
    uint64_t sample_index;
    int param_index;
    uint32_t value;
};

// Raw little-endian int32 samples, each holding a sign-extended 24-bit value.
std::vector<int32_t> read_stream(const std::string& path);
void write_stream(const std::string& path, const std::vector<int32_t>& samples);

// Whitespace-separated "sample_index param_index value" lines; '#' comments.
// Returned sorted by sample_index.
std::vector<ParamEvent> read_events(const std::string& path);

// Sign-extend a 24-bit field that Verilator hands back zero-extended in 32 bits.
inline int32_t sign_extend24(uint32_t v) {
    v &= 0xFFFFFFu;
    return static_cast<int32_t>(v >= 0x800000u ? v - 0x1000000u : v);
}

// Truncate a signed value to the 24-bit field the RTL port expects.
inline uint32_t to_field24(int32_t v) {
    return static_cast<uint32_t>(v) & 0xFFFFFFu;
}

}  // namespace wavsim
