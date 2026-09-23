`timescale 1ns / 1ps
`include "effect_contract.svh"

// reverb_top — harness wrapper for reverb.sv.
//
// No DSP here. It presents the standard interface from
// rtl/common/effect_contract.svh and slices the parameter bus onto the port
// names reverb.sv uses. Slot numbers match configs/effects/reverb.json.
//
//   slot 0  decay    Comb feedback. Higher = longer tail.
//   slot 1  damping  Lowpass inside the comb loop, so highs decay first.
//   slot 2  mix      Dry/wet balance.

module reverb_top (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [`SAMPLE_WIDTH-1:0] sample_in,
    input  logic                            sample_in_valid,
    input  logic [`PARAM_BUS_WIDTH-1:0]     params,

    output logic signed [`SAMPLE_WIDTH-1:0] sample_out,
    output logic                            sample_out_valid
);

    reverb u_reverb (
        .clk              (clk),
        .rst_n            (rst_n),
        .sample_in        (sample_in),
        .sample_in_valid  (sample_in_valid),
        .decay            (`PARAM(0)),
        .damping          (`PARAM(1)),
        .mix              (`PARAM(2)),

        .sample_out       (sample_out),
        .sample_out_valid (sample_out_valid)
    );

endmodule
