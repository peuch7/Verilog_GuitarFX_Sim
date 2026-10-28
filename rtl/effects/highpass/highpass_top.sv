`timescale 1ns / 1ps
`include "effect_contract.svh"

// Wrapper for the adjustable high-pass filter.
// Parameter slot 0 contains cutoff_hz.

module highpass_top (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [`SAMPLE_WIDTH-1:0] sample_in,
    input  logic                            sample_in_valid,
    input  logic [`PARAM_BUS_WIDTH-1:0]     params,

output logic signed [`SAMPLE_WIDTH-1:0] sample_out,
    output logic                            sample_out_valid
);

// Extract cutoff frequency from parameter slot 0.
    wire [15:0] cutoff_hz = params[15:0];

highpass u_highpass (
        .clk              (clk),
        .rst_n            (rst_n),
        .sample_in        (sample_in),
        .sample_in_valid  (sample_in_valid),
        .cutoff_hz        (cutoff_hz),

.sample_out       (sample_out),
        .sample_out_valid (sample_out_valid)
    );

endmodule
