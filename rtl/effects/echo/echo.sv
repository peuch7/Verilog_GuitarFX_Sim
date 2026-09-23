`timescale 1ns / 1ps
//
// echo.sv
//
// TODO (you): implement a fixed number of discrete decaying repeats (feed-forward taps)
//
// Right now this is a passthrough, so `wavsim run --effect echo` already works
// end to end. Replace the body below; keep the port list and the valid protocol.
//
// The protocol the harness relies on:
//   * sample_in_valid pulses high for one clock per input sample.
//   * Raise sample_out_valid for one clock per output sample you produce.
//   * Latency is yours to choose. If you need more than 32 clocks between
//     samples, raise "cycles_per_sample" in configs/effects/echo.json.
//
module echo (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [23:0]              sample_in,
    input  logic                            sample_in_valid,
    input  logic [15:0]                  delay_samples,  // Spacing between repeats.
    input  logic [15:0]                  decay,  // Amplitude ratio between consecutive repeats.
    input  logic [15:0]                  taps,  // How many repeats are generated.
    input  logic [15:0]                  mix,  // Dry/wet balance.

    output logic signed [23:0]              sample_out,
    output logic                            sample_out_valid
);

    // TODO: replace this passthrough with the real signal path.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            sample_out       <= '0;
            sample_out_valid <= 1'b0;
        end else begin
            sample_out       <= sample_in;
            sample_out_valid <= sample_in_valid;
        end
    end

endmodule
