`timescale 1ns / 1ps
//
// distortion.sv
//
// TODO (you): implement hard-clipping distortion with a tone control
//
// Right now this is a passthrough, so `wavsim run --effect distortion` already works
// end to end. Replace the body below; keep the port list and the valid protocol.
//
// The protocol the harness relies on:
//   * sample_in_valid pulses high for one clock per input sample.
//   * Raise sample_out_valid for one clock per output sample you produce.
//   * Latency is yours to choose. If you need more than 32 clocks between
//     samples, raise "cycles_per_sample" in configs/effects/distortion.json.
//
module distortion (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [23:0]              sample_in,
    input  logic                            sample_in_valid,
    input  logic [15:0]                  drive,  // Pre-clip gain. The clip threshold stays at full scale.
    input  logic [15:0]                  tone,  // 0 = dark (~800 Hz one-pole), 1 = open (~12 kHz).
    input  logic [15:0]                  level,  // Output attenuation, applied after clipping.

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
