`timescale 1ns / 1ps
`include "effect_contract.svh"

// distortion_top — harness wrapper for distortion.sv.
//
// No DSP here. It presents the standard interface from
// rtl/common/effect_contract.svh and slices the parameter bus onto the port
// names distortion.sv uses. Slot numbers match configs/effects/distortion.json.
//
//   slot 0  drive  Pre-clip gain. The clip threshold stays at full scale.
//   slot 1  tone   0 = dark (~800 Hz one-pole), 1 = open (~12 kHz).
//   slot 2  level  Output attenuation, applied after clipping.

module distortion_top (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [`SAMPLE_WIDTH-1:0] sample_in,
    input  logic                            sample_in_valid,
    input  logic [`PARAM_BUS_WIDTH-1:0]     params,

    output logic signed [`SAMPLE_WIDTH-1:0] sample_out,
    output logic                            sample_out_valid
);

    distortion u_distortion (
        .clk              (clk),
        .rst_n            (rst_n),
        .sample_in        (sample_in),
        .sample_in_valid  (sample_in_valid),
        .drive            (`PARAM(0)),
        .tone             (`PARAM(1)),
        .level            (`PARAM(2)),

        .sample_out       (sample_out),
        .sample_out_valid (sample_out_valid)
    );

endmodule
