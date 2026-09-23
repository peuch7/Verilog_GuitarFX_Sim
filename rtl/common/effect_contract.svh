// effect_contract.svh — the interface every effect wrapper must present.
//
// The testbench only ever talks to a module with this exact port list, which is
// what makes one harness work for delay, chorus, reverb and anything added later.
// Your own effect module keeps whatever ports you like; the thin
// <name>_top.sv wrapper maps them onto this.
//
//   module <name>_top (
//       input  logic                             clk,
//       input  logic                             rst_n,
//       input  logic signed [`SAMPLE_WIDTH-1:0]  sample_in,
//       input  logic                             sample_in_valid,
//       input  logic [`PARAM_BUS_WIDTH-1:0]      params,
//       output logic signed [`SAMPLE_WIDTH-1:0]  sample_out,
//       output logic                             sample_out_valid
//   );
//
// Rules the harness relies on:
//   * sample_in_valid is high for exactly one clk cycle per input sample.
//   * sample_out is only read on cycles where sample_out_valid is high, so you
//     may drive sample_out combinationally or every cycle; only the strobe matters.
//   * Latency is free. The harness measures it and flushes the pipeline at the end.
//   * rst_n is active low and held low for 16 cycles before the first sample.
//     Honour it if you have state; a module without a reset still works.
//
// Parameters are 8 slots of 16 bits, param i at params[16*i +: 16]. Use
// `PARAM(i) to slice one out. Give each slot a name in configs/effects/<name>.json
// so the CLI can take --param mix=0.5 instead of a magic number.

`ifndef EFFECT_CONTRACT_SVH
`define EFFECT_CONTRACT_SVH

`define SAMPLE_WIDTH     24
`define PARAM_WIDTH      16
`define N_PARAMS         8
`define PARAM_BUS_WIDTH  (`PARAM_WIDTH * `N_PARAMS)

// Slice parameter slot i out of the bus.
`define PARAM(i) params[`PARAM_WIDTH*(i) +: `PARAM_WIDTH]

// Audio sample rate the streams are generated at, for modules that need it.
`define SAMPLE_RATE_HZ   48000

`endif
