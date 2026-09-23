`timescale 1ns / 1ps
`include "effect_contract.svh"

// delay_top — harness wrapper for delay.sv.
//
// Nothing here does any DSP. Its only job is to present the standard interface
// from rtl/common/effect_contract.svh and slice the parameter bus onto the
// names delay.sv actually uses. The slot numbers match configs/effects/delay.json.
//
//   slot 0  delay_samples   0..48000 samples of delay
//   slot 1  feedback        Q16: how much of the delayed signal is fed back
//   slot 2  mix             Q16: 0 = dry only, 65535 = delayed only

module delay_top (
    input  logic                            clk,
    input  logic                            rst_n,
    input  logic signed [`SAMPLE_WIDTH-1:0] sample_in,
    input  logic                            sample_in_valid,
    input  logic [`PARAM_BUS_WIDTH-1:0]     params,

    output logic signed [`SAMPLE_WIDTH-1:0] sample_out,
    output logic                            sample_out_valid
);

    // delay.sv has no reset port. Reference it so lint does not flag an unused
    // input, and so the intent is obvious to the next person reading this.
    wire unused_rst_n = rst_n;

    delay u_delay (
        .clk              (clk),
        .sample_in        (sample_in),
        .sample_in_valid  (sample_in_valid),

        .delay_samples    (`PARAM(0)),
        .feedback         (`PARAM(1)),
        .mix              (`PARAM(2)),

        .sample_out       (sample_out),
        .sample_out_valid (sample_out_valid)
    );

endmodule
