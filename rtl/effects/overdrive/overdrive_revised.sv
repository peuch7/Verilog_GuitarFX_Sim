`timescale 1ns / 1ps
`include "tanh_lut.svh"
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


    input  logic [15:0]                  drive,  // Gain into the tanh curve. (8 bit decimal, therefore 256 = gain of 1.0)
    input  logic [15:0]                  tone,  // Same one-pole tilt as distortion.
    input  logic [15:0]                  level,  // Output attenuation.
    input  logic [15:0]                  asymmetry,  // 0 = symmetric; higher adds even harmonics.

    output logic signed [23:0]              sample_out,
    output logic                            sample_out_valid
);

    logic signed [40:0] driven_product;
    logic signed [23:0] driven_signal;

    // Stage 1: overdrive gain
    always_comb begin
        driven_product = sample_in * $signed({1'b0, drive});
    end


    logic signed [23:0] tanh_lut [0:255];
    logic signed [40:0] lut_position;

    logic [7:0] lut_index;
    logic [7:0] interp_frac;

    logic signed [23:0] y0;
    logic signed [23:0] y1;

    logic signed [23:0] delta;
    logic signed [32:0] interp_product;
    logic signed [23:0] interpolated;

    // STage 2: tanh clipping
    always_comb begin

        lut_position   = '0;
        lut_index      = '0;
        interp_frac    = '0;
        y0             = '0;
        y1             = '0;
        delta          = '0;
        interp_product = '0;
        interpolated   = '0;

        // clipping +-4
        if (driven_signal <= -(24'sd1 <<< (2+14))) begin
            interpolated = {
                tanh_lut[0][23],
                tanh_lut[0]
            };
        end 
        
        else if(driven_signal >= (24'sd1 <<< (2+14))) begin
            interpolated = {
                tanh_lut[255][23],
                tanh_lut[255]
            };
        end 
        else begin

            lut_position = $signed(driven_signal) + (25'sd4 <<< 14);

            lut_index   = lut_position[16:9];
            interp_frac = lut_position[8:1];

            y0 = tanh_lut[lut_index];

            if (lut_index == 8'd255)
                y1 = tanh_lut[255];
            else
                y1 = tanh_lut[lut_index + 1'b1];

            delta = $signed({y1[23], y1})
                - $signed({y0[23], y0});

            interp_product =
                delta * $signed({1'b0, interp_frac});

            interpolated =
                y0 + (interp_product >>> 8);

        end

    end

    logic driven_valid;

    always_ff @(posedge clk) begin

        if (!rst_n) begin
            driven_valid     <= 1'b0;
            sample_out       <= '0;
            sample_out_valid <= 1'b0;
        end else begin
            
            if (sample_in_valid) begin
                driven_signal <= driven_product >>> 17;
                driven_valid <= 1'b1;
            end else begin
                driven_valid <= 1'b0;
            end
            
            if(driven_valid) begin
                sample_out <= interpolated;
            end

            sample_out_valid <= driven_valid;

        end



    end


endmodule
