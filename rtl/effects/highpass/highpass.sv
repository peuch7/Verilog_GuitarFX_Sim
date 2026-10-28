
`timescale 1ns / 1ps

//
// First-order IIR High-Pass Filter
// Adjustable cutoff frequency: 100 - 10000 Hz
// Sample rate: 48000 Hz
//
// Equation:
// y[n] = alpha * (y[n-1] + x[n] - x[n-1])
//
// alpha = 7639 / (cutoff_hz + 7639)
// Fixed-point coefficient uses Q15 format.
//

module highpass (
    input  logic               clk,
    input  logic               rst_n,
    input  logic signed [23:0] sample_in,
    input  logic               sample_in_valid,
    input  logic        [15:0] cutoff_hz,

    output logic signed [23:0] sample_out,
    output logic               sample_out_valid
);

    localparam int unsigned RC_CONSTANT = 7639;
    localparam int unsigned Q15_SCALE   = 32768;

    // Filter state
    logic signed [23:0] x_prev;
    logic signed [23:0] y_prev;

    // Cutoff frequency and coefficient
    logic [15:0] cutoff_clamped;
    logic [15:0] alpha_q15;

    // Intermediate calculations
    logic signed [25:0] difference_and_feedback;
    logic signed [42:0] product;
    logic signed [42:0] rounded_result;
    logic signed [23:0] y_next;

    // Clamp cutoff frequency
    always_comb begin
        if (cutoff_hz < 16'd100)
            cutoff_clamped = 16'd100;
        else if (cutoff_hz > 16'd10000)
            cutoff_clamped = 16'd10000;
        else
            cutoff_clamped = cutoff_hz;
    end

    // Calculate alpha using Q15 fixed-point arithmetic
    always_comb begin
        alpha_q15 =
            (RC_CONSTANT * Q15_SCALE) /
            (RC_CONSTANT + cutoff_clamped);
    end

    // High-pass filter calculation
    always_comb begin

        // Extend to 26 bits before arithmetic
        difference_and_feedback =
            $signed({{2{sample_in[23]}}, sample_in}) -
            $signed({{2{x_prev[23]}}, x_prev}) +
            $signed({{2{y_prev[23]}}, y_prev});

        // Multiply by the fixed-point coefficient
        product =
            difference_and_feedback *
            $signed({1'b0, alpha_q15});

        // Divide by 2^15 with symmetric rounding
        if (product < 0)
            rounded_result =
                -(((-product) + 43'sd16384) >>> 15);
        else
            rounded_result =
                ((product + 43'sd16384) >>> 15);

        // Saturate to signed 24-bit output
        if (rounded_result > 43'sd8388607)
            y_next = 24'sh7fffff;
        else if (rounded_result < -43'sd8388608)
            y_next = 24'sh800000;
        else
            y_next = rounded_result[23:0];

    end

    // Update only when a new sample arrives
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            x_prev           <= '0;
            y_prev           <= '0;
            sample_out       <= '0;
            sample_out_valid <= 1'b0;
        end else begin
            sample_out_valid <= sample_in_valid;

            if (sample_in_valid) begin
                x_prev     <= sample_in;
                y_prev     <= y_next;
                sample_out <= y_next;
            end
        end
    end

endmodule
