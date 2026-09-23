`timescale 1ns / 1ps
//
// reverb.sv
//
// TODO (you): implement Schroeder reverb: four parallel combs into two allpass stages
//
// Right now this is a passthrough, so `wavsim run --effect reverb` already works
// end to end. Replace the body below; keep the port list and the valid protocol.
//
// The protocol the harness relies on:
//   * sample_in_valid pulses high for one clock per input sample.
//   * Raise sample_out_valid for one clock per output sample you produce.
//   * Latency is yours to choose. If you need more than 32 clocks between
//     samples, raise "cycles_per_sample" in configs/effects/reverb.json.
//
module reverb (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [23:0]              sample_in,
    input  logic                            sample_in_valid,
    input  logic [15:0]                  decay,  // Comb feedback. Higher = longer tail.
    input  logic [15:0]                  damping,  // Lowpass inside the comb loop, so highs decay first.
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
