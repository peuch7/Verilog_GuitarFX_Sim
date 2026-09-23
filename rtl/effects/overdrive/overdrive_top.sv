`timescale 1ns / 1ps
`include "effect_contract.svh"

// overdrive_top — harness wrapper for overdrive.sv.
//
// No DSP here. It presents the standard interface from
// rtl/common/effect_contract.svh and slices the parameter bus onto the port
// names overdrive.sv uses. Slot numbers match configs/effects/overdrive.json.
//
//   slot 0  drive      Gain into the tanh curve.
//   slot 1  tone       Same one-pole tilt as distortion.
//   slot 2  level      Output attenuation.
//   slot 3  asymmetry  0 = symmetric; higher adds even harmonics.

module overdrive_top (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [`SAMPLE_WIDTH-1:0] sample_in,
    input  logic                            sample_in_valid,
    input  logic [`PARAM_BUS_WIDTH-1:0]     params,

    output logic signed [`SAMPLE_WIDTH-1:0] sample_out,
    output logic                            sample_out_valid
);

    overdrive u_overdrive (
        .clk              (clk),
        .rst_n            (rst_n),
        .sample_in        (sample_in),
        .sample_in_valid  (sample_in_valid),
        .drive            (`PARAM(0)),
        .tone             (`PARAM(1)),
        .level            (`PARAM(2)),
        .asymmetry        (`PARAM(3)),

        .sample_out       (sample_out),
        .sample_out_valid (sample_out_valid)
    );

endmodule
