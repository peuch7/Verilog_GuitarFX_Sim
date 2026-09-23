`timescale 1ns / 1ps
`include "effect_contract.svh"

// echo_top — harness wrapper for echo.sv.
//
// No DSP here. It presents the standard interface from
// rtl/common/effect_contract.svh and slices the parameter bus onto the port
// names echo.sv uses. Slot numbers match configs/effects/echo.json.
//
//   slot 0  delay_samples  Spacing between repeats.
//   slot 1  decay          Amplitude ratio between consecutive repeats.
//   slot 2  taps           How many repeats are generated.
//   slot 3  mix            Dry/wet balance.

module echo_top (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [`SAMPLE_WIDTH-1:0] sample_in,
    input  logic                            sample_in_valid,
    input  logic [`PARAM_BUS_WIDTH-1:0]     params,

    output logic signed [`SAMPLE_WIDTH-1:0] sample_out,
    output logic                            sample_out_valid
);

    echo u_echo (
        .clk              (clk),
        .rst_n            (rst_n),
        .sample_in        (sample_in),
        .sample_in_valid  (sample_in_valid),
        .delay_samples    (`PARAM(0)),
        .decay            (`PARAM(1)),
        .taps             (`PARAM(2)),
        .mix              (`PARAM(3)),

        .sample_out       (sample_out),
        .sample_out_valid (sample_out_valid)
    );

endmodule
