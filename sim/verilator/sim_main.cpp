// Generic Verilator harness: drives any module that implements the interface in
// rtl/common/effect_contract.svh with a stream of 24-bit samples.
//
// There is no codegen here. The Makefile picks the device under test by passing
//   -DDUT_HEADER='"Vdelay_top.h"' -DDUT_TYPE=Vdelay_top
// so this one file serves every effect in the project.
//
// Timing model: sample_in_valid is pulsed for one cycle every
// --cycles-per-sample clocks. Real hardware runs ~2083 clocks per sample at
// 100 MHz / 48 kHz; simulating that ratio would be almost entirely idle cycles,
// so the gap is shrunk to just more than the DUT's pipeline latency. Effects
// needing more room raise cycles_per_sample in their manifest.

#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "verilated.h"
#if VM_TRACE
#include "verilated_vcd_c.h"
#endif

#include DUT_HEADER
#include "stream_io.h"

using Dut = DUT_TYPE;
using wavsim::ParamEvent;

namespace {

constexpr int kNumParams = 8;
constexpr int kResetCycles = 16;

struct Options {
    std::string in_path;
    std::string out_path;
    std::string automation_path;
    std::string trace_path;
    std::string stats_path;
    uint32_t params[kNumParams] = {0, 0, 0, 0, 0, 0, 0, 0};
    uint64_t cycles_per_sample = 32;
    uint64_t flush_samples = 16;
    uint64_t max_samples = 0;  // 0 = no limit
    bool quiet = false;
};

[[noreturn]] void usage(const char* argv0, int code) {
    std::fprintf(stderr,
        "usage: %s --in <stream> --out <stream> [options]\n"
        "\n"
        "  --in PATH              input sample stream (raw little-endian int32)\n"
        "  --out PATH             output sample stream\n"
        "  --params a,b,c,...     up to 8 decimal values for the parameter bus\n"
        "  --cycles-per-sample N  clocks between sample_in_valid pulses (default 32)\n"
        "  --flush-samples N      sample periods to clock after the last input (default 16)\n"
        "  --max-samples N        stop after N input samples (0 = all)\n"
        "  --automation PATH      'sample_index param_index value' lines\n"
        "  --trace PATH           write a VCD (requires a TRACE=1 build)\n"
        "  --stats PATH           write a JSON run summary\n"
        "  --quiet                suppress the summary on stderr\n",
        argv0);
    std::exit(code);
}

const char* need_value(int argc, char** argv, int& i, const char* argv0) {
    if (i + 1 >= argc) {
        std::fprintf(stderr, "error: %s needs a value\n", argv[i]);
        usage(argv0, 2);
    }
    return argv[++i];
}

void parse_params(const char* text, uint32_t* out, const char* argv0) {
    std::string s(text);
    size_t start = 0;
    int index = 0;
    while (start <= s.size() && index < kNumParams) {
        size_t comma = s.find(',', start);
        std::string field = s.substr(start, comma == std::string::npos ? std::string::npos
                                                                       : comma - start);
        if (!field.empty()) {
            long value = std::strtol(field.c_str(), nullptr, 0);
            if (value < 0 || value > 0xFFFF) {
                std::fprintf(stderr, "error: param %d value %ld outside 0..65535\n",
                             index, value);
                usage(argv0, 2);
            }
            out[index] = static_cast<uint32_t>(value);
        }
        ++index;
        if (comma == std::string::npos) break;
        start = comma + 1;
    }
}

Options parse_args(int argc, char** argv) {
    Options opt;
    for (int i = 1; i < argc; ++i) {
        const char* a = argv[i];
        if (!std::strcmp(a, "--in")) opt.in_path = need_value(argc, argv, i, argv[0]);
        else if (!std::strcmp(a, "--out")) opt.out_path = need_value(argc, argv, i, argv[0]);
        else if (!std::strcmp(a, "--params")) parse_params(need_value(argc, argv, i, argv[0]), opt.params, argv[0]);
        else if (!std::strcmp(a, "--cycles-per-sample")) opt.cycles_per_sample = std::strtoull(need_value(argc, argv, i, argv[0]), nullptr, 0);
        else if (!std::strcmp(a, "--flush-samples")) opt.flush_samples = std::strtoull(need_value(argc, argv, i, argv[0]), nullptr, 0);
        else if (!std::strcmp(a, "--max-samples")) opt.max_samples = std::strtoull(need_value(argc, argv, i, argv[0]), nullptr, 0);
        else if (!std::strcmp(a, "--automation")) opt.automation_path = need_value(argc, argv, i, argv[0]);
        else if (!std::strcmp(a, "--trace")) opt.trace_path = need_value(argc, argv, i, argv[0]);
        else if (!std::strcmp(a, "--stats")) opt.stats_path = need_value(argc, argv, i, argv[0]);
        else if (!std::strcmp(a, "--quiet")) opt.quiet = true;
        else if (!std::strcmp(a, "--help") || !std::strcmp(a, "-h")) usage(argv[0], 0);
        else if (!std::strncmp(a, "+verilator", 10)) continue;  // consumed by the runtime
        else {
            std::fprintf(stderr, "error: unknown option %s\n", a);
            usage(argv[0], 2);
        }
    }
    if (opt.in_path.empty() || opt.out_path.empty()) usage(argv[0], 2);
    if (opt.cycles_per_sample == 0) {
        std::fprintf(stderr, "error: --cycles-per-sample must be at least 1\n");
        std::exit(2);
    }
    return opt;
}

// The contract fixes the parameter bus at 8 x 16 = 128 bits, which Verilator
// presents as a 4-word array. Slot i lives in word i/2, half (i%2).
void write_param(Dut& dut, int index, uint32_t value) {
    const int word = index / 2;
    const int shift = (index % 2) * 16;
    uint32_t w = dut.params[word];
    w &= ~(0xFFFFu << shift);
    w |= (value & 0xFFFFu) << shift;
    dut.params[word] = w;
}

}  // namespace

int main(int argc, char** argv) {
    Options opt = parse_args(argc, argv);

    std::vector<int32_t> input;
    std::vector<ParamEvent> events;
    try {
        input = wavsim::read_stream(opt.in_path);
        if (!opt.automation_path.empty()) events = wavsim::read_events(opt.automation_path);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "error: %s\n", e.what());
        return 1;
    }
    if (opt.max_samples && input.size() > opt.max_samples) input.resize(opt.max_samples);

    auto contextp = std::make_unique<VerilatedContext>();
    contextp->commandArgs(argc, argv);
    auto dut = std::make_unique<Dut>(contextp.get(), "dut");

#if VM_TRACE
    std::unique_ptr<VerilatedVcdC> tfp;
    if (!opt.trace_path.empty()) {
        contextp->traceEverOn(true);
        tfp = std::make_unique<VerilatedVcdC>();
        dut->trace(tfp.get(), 99);
        tfp->open(opt.trace_path.c_str());
    }
#else
    if (!opt.trace_path.empty()) {
        std::fprintf(stderr,
                     "error: --trace needs a tracing build; rebuild with TRACE=1\n");
        return 2;
    }
#endif

    uint64_t sim_time = 0;
    auto half_step = [&](int level) {
        dut->clk = level;
        dut->eval();
#if VM_TRACE
        if (tfp) tfp->dump(sim_time);
#endif
        ++sim_time;
        contextp->timeInc(1);
    };
    // One clock: settle inputs low, then rise. Registered outputs are readable
    // after the rising half completes.
    auto tick = [&]() { half_step(0); half_step(1); };

    for (int i = 0; i < kNumParams; ++i) write_param(*dut, i, opt.params[i]);
    dut->sample_in = 0;
    dut->sample_in_valid = 0;
    dut->rst_n = 0;
    for (int i = 0; i < kResetCycles; ++i) tick();
    dut->rst_n = 1;
    // One idle cycle with reset released before the first sample, so the Icarus
    // testbench can reproduce this sequence exactly and crosscheck stays valid.
    tick();

    std::vector<int32_t> output;
    output.reserve(input.size() + opt.flush_samples + 1);

    uint64_t cycle = 0;
    size_t in_index = 0;
    size_t event_index = 0;
    uint64_t first_in_cycle = 0;
    uint64_t first_out_cycle = 0;
    bool saw_input = false;
    bool saw_output = false;

    const uint64_t flush_cycles = opt.flush_samples * opt.cycles_per_sample;
    uint64_t flush_left = flush_cycles;

    while (in_index < input.size() || flush_left > 0) {
        // Apply any parameter changes scheduled for the sample about to go in.
        while (event_index < events.size() && events[event_index].sample_index <= in_index) {
            const ParamEvent& ev = events[event_index];
            write_param(*dut, ev.param_index, ev.value);
            ++event_index;
        }

        const bool feed = (cycle % opt.cycles_per_sample == 0) && in_index < input.size();
        dut->sample_in_valid = feed ? 1 : 0;
        dut->sample_in = feed ? wavsim::to_field24(input[in_index]) : 0;

        tick();

        if (feed) {
            if (!saw_input) { first_in_cycle = cycle; saw_input = true; }
            ++in_index;
        }
        if (dut->sample_out_valid) {
            if (!saw_output) { first_out_cycle = cycle; saw_output = true; }
            output.push_back(wavsim::sign_extend24(dut->sample_out));
        }
        if (in_index >= input.size() && flush_left > 0) --flush_left;
        ++cycle;
    }

    dut->final();
#if VM_TRACE
    if (tfp) tfp->close();
#endif

    try {
        wavsim::write_stream(opt.out_path, output);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "error: %s\n", e.what());
        return 1;
    }

    const int64_t latency_cycles =
        (saw_input && saw_output) ? static_cast<int64_t>(first_out_cycle - first_in_cycle) : -1;
    const double latency_samples =
        latency_cycles < 0 ? -1.0
                           : static_cast<double>(latency_cycles) / static_cast<double>(opt.cycles_per_sample);

    if (!opt.quiet) {
        std::fprintf(stderr,
                     "verilator: %zu in -> %zu out, %" PRIu64 " cycles, latency %" PRId64
                     " cycles (%.2f samples)\n",
                     input.size(), output.size(), cycle, latency_cycles, latency_samples);
    }

    if (!opt.stats_path.empty()) {
        std::FILE* f = std::fopen(opt.stats_path.c_str(), "wb");
        if (!f) {
            std::fprintf(stderr, "error: cannot write stats to %s\n", opt.stats_path.c_str());
            return 1;
        }
        std::fprintf(f,
                     "{\n"
                     "  \"backend\": \"verilator\",\n"
                     "  \"samples_in\": %zu,\n"
                     "  \"samples_out\": %zu,\n"
                     "  \"cycles\": %" PRIu64 ",\n"
                     "  \"cycles_per_sample\": %" PRIu64 ",\n"
                     "  \"latency_cycles\": %" PRId64 ",\n"
                     "  \"latency_samples\": %.4f\n"
                     "}\n",
                     input.size(), output.size(), cycle, opt.cycles_per_sample,
                     latency_cycles, latency_samples);
        std::fclose(f);
    }

    return 0;
}
