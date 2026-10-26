
`timescale 1ns / 1ps

//
// First-order IIR Low-Pass Filter
// Adjustable cutoff frequency: 100 - 10000 Hz
// Sample rate: 48000 Hz
//
// Equation:
// y[n] = y[n-1] + alpha * (x[n] - y[n-1])
//
// alpha = cutoff_hz / (cutoff_hz + 7639)
// Fixed-point coefficient uses Q15 format.
//

module lowpass (
    input  logic               clk,
    input  logic               rst_n,
    input  logic signed [23:0] sample_in,
    input  logic               sample_in_valid,
    input  logic        [15:0] cutoff_hz,

    output logic signed [23:0] sample_out,
    output logic               sample_out_valid
);

    localparam int unsigned RC_CONSTANT = 7639;
    localparam int unsigned Q15_SCALE = 32768;

    // Filter state
    logic signed [23:0] y_prev;

    // Cutoff frequency and coefficient
    logic [15:0] cutoff_clamped;
    logic [15:0] alpha_q15;

    // Intermediate calculations
    logic signed [24:0] difference;
    logic signed [41:0] product;
    logic signed [41:0] increment;
    logic signed [24:0] y_next;

    // Clamp cutoff frequency
    always_comb begin
        if (cutoff_hz < 100)
            cutoff_clamped = 16'd100;
        else if (cutoff_hz > 10000)
            cutoff_clamped = 16'd10000;
        else
            cutoff_clamped = cutoff_hz;
    end

    // Calculate alpha using Q15 fixed-point arithmetic
    always_comb begin
        alpha_q15 =
            (32'(cutoff_clamped) * Q15_SCALE) /
            (32'(cutoff_clamped) + RC_CONSTANT);
    end

    // Low-pass filter calculation
    always_comb begin

        // Extend to 25 bits before subtraction
        difference =
            $signed({sample_in[23], sample_in}) -
            $signed({y_prev[23], y_prev});

        // Multiply by the fixed-point coefficient
        product =
            difference * $signed({1'b0, alpha_q15});

        // Divide by 2^15
        increment = product >>> 15;

        // Add to previous filtered output
        y_next =
            $signed({y_prev[23], y_prev}) +
            $signed(increment[24:0]);

    end

    // Update only when a new sample arrives
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            y_prev           <= '0;
            sample_out       <= '0;
            sample_out_valid <= 1'b0;
        end else begin
            sample_out_valid <= sample_in_valid;

            if (sample_in_valid) begin
                y_prev    <= y_next[23:0];
                sample_out <= y_next[23:0];
            end
        end
    end

endmodule
