`timescale 1ns / 1ps
//
// chorus.sv
//
// TODO (you): implement LFO-modulated short delay mixed with the dry signal
//
// Right now this is a passthrough, so `wavsim run --effect chorus` already works
// end to end. Replace the body below; keep the port list and the valid protocol.
//
// The protocol the harness relies on:
//   * sample_in_valid pulses high for one clock per input sample.
//   * Raise sample_out_valid for one clock per output sample you produce.
//   * Latency is yours to choose. If you need more than 32 clocks between
//     samples, raise "cycles_per_sample" in configs/effects/chorus.json.
//
module chorus (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [23:0]              sample_in,
    input  logic                            sample_in_valid,
    input  logic [15:0]                  rate,  // LFO frequency. Stored in centi-hertz: 100 = 1.00 Hz.
    input  logic [15:0]                  depth,  // Peak sweep either side of base_ms. Stored in 0.1 ms steps.
    input  logic [15:0]                  mix,  // Dry/wet balance.
    input  logic [15:0]                  base_ms,  // Centre delay. Stored in 0.1 ms steps.

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
