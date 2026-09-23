`timescale 1ns / 1ps
//
// overdrive.sv
//
// TODO (you): implement soft-clipping (tanh) overdrive
//
// Right now this is a passthrough, so `wavsim run --effect overdrive` already works
// end to end. Replace the body below; keep the port list and the valid protocol.
//
// The protocol the harness relies on:
//   * sample_in_valid pulses high for one clock per input sample.
//   * Raise sample_out_valid for one clock per output sample you produce.
//   * Latency is yours to choose. If you need more than 32 clocks between
//     samples, raise "cycles_per_sample" in configs/effects/overdrive.json.
//
module overdrive (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [23:0]              sample_in,
    input  logic                            sample_in_valid,
    input  logic [15:0]                  drive,  // Gain into the tanh curve.
    input  logic [15:0]                  tone,  // Same one-pole tilt as distortion.
    input  logic [15:0]                  level,  // Output attenuation.
    input  logic [15:0]                  asymmetry,  // 0 = symmetric; higher adds even harmonics.

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
