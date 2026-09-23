`timescale 1ns / 1ps
`include "effect_contract.svh"

// chorus_top — harness wrapper for chorus.sv.
//
// No DSP here. It presents the standard interface from
// rtl/common/effect_contract.svh and slices the parameter bus onto the port
// names chorus.sv uses. Slot numbers match configs/effects/chorus.json.
//
//   slot 0  rate     LFO frequency. Stored in centi-hertz: 100 = 1.00 Hz.
//   slot 1  depth    Peak sweep either side of base_ms. Stored in 0.1 ms steps.
//   slot 2  mix      Dry/wet balance.
//   slot 3  base_ms  Centre delay. Stored in 0.1 ms steps.

module chorus_top (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [`SAMPLE_WIDTH-1:0] sample_in,
    input  logic                            sample_in_valid,
    input  logic [`PARAM_BUS_WIDTH-1:0]     params,

    output logic signed [`SAMPLE_WIDTH-1:0] sample_out,
    output logic                            sample_out_valid
);

    chorus u_chorus (
        .clk              (clk),
        .rst_n            (rst_n),
        .sample_in        (sample_in),
        .sample_in_valid  (sample_in_valid),
        .rate             (`PARAM(0)),
        .depth            (`PARAM(1)),
        .mix              (`PARAM(2)),
        .base_ms          (`PARAM(3)),

        .sample_out       (sample_out),
        .sample_out_valid (sample_out_valid)
    );

endmodule
