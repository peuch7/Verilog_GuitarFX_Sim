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

    // TODO: replace this passthrough with the real signal path.
    logic signed [40:0] driven_sample;
    logic driven_valid;

    logic signed [23:0] tanh_lut [0:255];
    logic signed [40:0] lut_position;

    logic [7:0] lut_index;
    logic [7:0] interp_frac;

    logic signed [23:0] y0;
    logic signed [23:0] y1;

    logic signed [24:0] delta;
    logic signed [33:0] interp_product;
    logic signed [24:0] interpolated;


    initial begin
        tanh_lut = `TANH_TABLE;
    end

    always_comb begin

        lut_position   = '0;
        lut_index      = '0;
        interp_frac    = '0;
        y0             = '0;
        y1             = '0;
        delta          = '0;
        interp_product = '0;
        interpolated   = '0;

        // x <= -4
        if (driven_sample <= -(41'sd1 <<< 33)) begin

            interpolated = {
                tanh_lut[0][23],
                tanh_lut[0]
            };

        end

        // x >= +4
        else if (driven_sample >= (41'sd1 <<< 33)) begin

            interpolated = {
                tanh_lut[255][23],
                tanh_lut[255]
            };

        end

        // -4 < x < +4
        else begin

            // Move [-4,4) -> [0,8)
            lut_position =
                driven_sample + (41'sd1 <<< 33);

            // Integer LUT index
            lut_index =
                lut_position >>> 26;

            // 8-bit fractional position within interval
            interp_frac =
                lut_position[25:18];

            // Surrounding LUT values
            y0 = tanh_lut[lut_index];

            if (lut_index == 8'd255)
                y1 = tanh_lut[255];
            else
                y1 = tanh_lut[lut_index + 1'b1];

            // Difference between LUT points
            delta =
                $signed({y1[23], y1})
                - $signed({y0[23], y0});

            // Multiply by Q0.8 interpolation fraction
            interp_product =
                delta * $signed({1'b0, interp_frac});

            // y = y0 + fraction*(y1-y0)
            interpolated =
                $signed({y0[23], y0})
                + (interp_product >>> 8);

        end

    end

    logic signed [40:0] level_product;

    always_comb begin
        level_product = $signed(interpolated[23:0]) * $signed({1'b0, level});
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            driven_sample    <= '0;
            driven_valid     <= 1'b0;
            sample_out       <= '0;
            sample_out_valid <= 1'b0;
        end else begin

            // Stage 1: multiply by drive
            if (sample_in_valid) begin
                driven_sample <=
                    sample_in * $signed({1'b0, drive});
            end

            driven_valid <= sample_in_valid;

            // Stage 2: convert Q31 product back to Q23 audio
            if (driven_valid) begin
                sample_out <= level_product >>> 16;
            end

            sample_out_valid <= driven_valid;
        end
    end

endmodule
